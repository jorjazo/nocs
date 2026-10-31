"""PHD2 for the active profile: the connection to it, its settings, and its state (ADR 0022).

State layout under ``("guiding",)``::

    phd2:      {host, port, connected, version, error}
    managed:   whether nocsd writes PHD2's settings (NOCS_PHD2_SETTINGS)
    settings:  none | pending | applying | applied | failed | user
    profile:   the PHD2 profile in use, by name
    app_state: PHD2's own state (Stopped, Selected, Looping, Calibrating, Guiding,
               LostLock, Paused), or None while unknown
    error:     why PHD2 does not run the profile's settings, or None

When nocsd manages the settings, it renders them from the active profile once its
guide camera and mount are ready. If PHD2 runs another profile, nocsd writes the
file and asks PHD2 to shut down; PHD2's service imports the file as it starts
again. That never happens while PHD2 is busy: the change waits until it stops.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from enum import StrEnum
from pathlib import Path as FsPath

import anyio

from nocs.devices import Camera, DeviceError, Mount
from nocs.equipment import EquipmentService, Role
from nocs.equipment.profiles import write_atomic
from nocs.equipment.service import IndiConnection
from nocs.guiding.phd2 import Phd2Client, Phd2ConnectionError, Phd2Error, Phd2Event, Phd2Message
from nocs.guiding.settings import GuideRig, Phd2Settings, render
from nocs.indi import IndiClient
from nocs.state import Json, Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("guiding",)
_BACKOFF = (1.0, 2.0, 5.0, 10.0)
RESTART_BACKOFF = 1.0
"""How soon to look for PHD2 again after asking it to restart…"""
RESTART_ATTEMPTS = 20
"""…and for how many attempts, before the usual backoff."""

IDLE_STATES = frozenset({"Stopped", "Selected"})
"""PHD2 states in which it may be restarted."""

_STATE_OF_EVENT = {
    "LoopingExposures": "Looping",
    "LoopingExposuresStopped": "Stopped",
    "StartCalibration": "Calibrating",
    "Calibrating": "Calibrating",
    "GuideStep": "Guiding",
    "GuidingStopped": "Stopped",
    "StarLost": "LostLock",
    "Paused": "Paused",
}
"""Events that tell PHD2's state unambiguously."""
_QUERY_EVENTS = frozenset(
    {"StartGuiding", "Resumed", "StarSelected", "CalibrationComplete", "CalibrationFailed"}
)
"""Events after which PHD2's state is asked for."""


class SettingsStatus(StrEnum):
    NONE = "none"
    """Nothing to apply: no profile connected, or its guide camera or mount not ready."""
    PENDING = "pending"
    """Waiting for PHD2 to be reachable and stopped."""
    APPLYING = "applying"
    """PHD2 was asked to restart with new settings."""
    APPLIED = "applied"
    FAILED = "failed"
    USER = "user"
    """nocsd does not manage PHD2's settings."""


class GuidingService:
    def __init__(
        self,
        store: StateStore,
        equipment: EquipmentService,
        bridge: IndiConnection,
        *,
        host: str,
        port: int,
        settings_file: FsPath | None,
        indi_host: str,
        indi_port: int,
    ) -> None:
        self._store = store
        self._equipment = equipment
        self._host = host
        self._port = port
        self._settings_file = settings_file
        self._indi_host = indi_host
        self._indi_port = indi_port
        self._indi: IndiClient | None = bridge.client
        self._phd2: Phd2Client | None = None
        self._app_state: str | None = None
        self._desired: Phd2Settings | None = None
        self._desired_error: str | None = None
        self._attempted: str | None = None
        """Name of the settings PHD2 was last restarted for."""
        self._changed = asyncio.Event()

        store.set(
            ROOT,
            {
                "phd2": self._server(connected=False),
                "managed": settings_file is not None,
                "settings": (SettingsStatus.NONE if settings_file else SettingsStatus.USER).value,
                "profile": None,
                "app_state": None,
                "error": None,
            },
        )
        self._unwatch_bridge = bridge.watch(self._on_indi)
        self._unwatch_equipment = equipment.add_listener(self._refresh)
        self._refresh()

    @property
    def managed(self) -> bool:
        return self._settings_file is not None

    @property
    def settings(self) -> Phd2Settings | None:
        """What PHD2 should run for the active profile, when nocsd manages it."""
        return self._desired

    @property
    def phd2(self) -> Phd2Client | None:
        """The connected PHD2, if any."""
        return self._phd2 if self._phd2 is not None and self._phd2.connected else None

    async def run(self) -> None:
        """Stay connected to PHD2 until cancelled, retrying with backoff."""
        attempt = 0
        while True:
            client = Phd2Client(self._host, self._port)
            closed = False

            def on_message(message: Phd2Message) -> None:
                nonlocal closed
                if isinstance(message, Phd2Event):
                    self._on_event(message)
                else:
                    closed = True
                    self._changed.set()

            client.add_listener(on_message)
            try:
                await client.connect()
            except (OSError, TimeoutError) as e:
                self._publish_server(connected=False, error=str(e) or type(e).__name__)
            else:
                attempt = 0
                self._phd2 = client
                self._publish_server(connected=True)
                log.info("connected to PHD2 at %s:%s", self._host, self._port)
                try:
                    while not closed:
                        await self._sync(client)
                        await self._changed.wait()
                        self._changed.clear()
                except Phd2ConnectionError:
                    pass
                finally:
                    self._phd2 = None
                    self._app_state = None
                    await client.close()
                    self._publish_server(connected=False)
                    with self._store.transaction():
                        self._store.set((*ROOT, "app_state"), None)
                        self._store.set((*ROOT, "profile"), None)
                log.info("lost connection to PHD2")
            restarting = self._status() is SettingsStatus.APPLYING
            if restarting and attempt < RESTART_ATTEMPTS:
                delay = RESTART_BACKOFF
            else:
                delay = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

    def close(self) -> None:
        self._unwatch_bridge()
        self._unwatch_equipment()

    # -- internals ----------------------------------------------------------

    async def _sync(self, client: Phd2Client) -> None:
        """Bring PHD2's settings in line with the active profile, as far as it can now."""
        try:
            state = await client.call("get_app_state")
            if isinstance(state, str):
                self._set_app_state(state, wake=False)
            if not self.managed:
                await self._check_equipment(client)
                return
            profile = await client.call("get_profile")
            name = profile.get("name") if isinstance(profile, dict) else None
            self._store.set((*ROOT, "profile"), name if isinstance(name, str) else None)
        except Phd2Error as e:
            log.warning("PHD2: %s", e)
            self._publish_settings(SettingsStatus.FAILED, str(e))
            return
        desired = self._desired
        if desired is None:
            self._publish_settings(SettingsStatus.NONE, self._desired_error)
        elif name == desired.profile_name:
            self._attempted = None
            self._publish_settings(SettingsStatus.APPLIED)
        elif self._app_state not in IDLE_STATES:
            self._publish_settings(SettingsStatus.PENDING)
        elif self._attempted == desired.profile_name:
            self._publish_settings(
                SettingsStatus.FAILED,
                f"PHD2 restarted without the new settings: its service must import "
                f"{self._settings_file} (PHD2_SETTINGS)",
            )
        else:
            await self._apply(client, desired)

    async def _apply(self, client: Phd2Client, desired: Phd2Settings) -> None:
        assert self._settings_file is not None
        path = self._settings_file
        try:
            await anyio.to_thread.run_sync(_write_settings, path, desired.content)
        except OSError as e:
            self._publish_settings(SettingsStatus.FAILED, f"cannot write {path}: {e}")
            return
        log.info("restarting PHD2 with settings %s", desired.profile_name)
        self._attempted = desired.profile_name
        self._publish_settings(SettingsStatus.APPLYING)
        # PHD2 may close the connection before answering.
        with contextlib.suppress(Phd2ConnectionError, TimeoutError):
            await client.call("shutdown", timeout=5)

    async def _check_equipment(self, client: Phd2Client) -> None:
        """With PHD2 as the user set it up, say when it guides with other devices."""
        current = await client.call("get_current_equipment")
        wanted = {
            "camera": self._equipment.ready_device(Role.GUIDE_CAMERA),
            "mount": self._equipment.ready_device(Role.MOUNT),
        }
        problems: list[str] = []
        for kind, device in wanted.items():
            if device is None:
                continue
            entry = current.get(kind) if isinstance(current, dict) else None
            selected = entry.get("name") if isinstance(entry, dict) else None
            if not isinstance(selected, str) or f"[{device}]" not in selected:
                problems.append(f"PHD2's {kind} is {selected or 'not set'}, not {device}")
        self._publish_settings(SettingsStatus.USER, "; ".join(problems) or None)

    def _on_indi(self, client: IndiClient | None) -> None:
        self._indi = client
        self._refresh()

    def _refresh(self) -> None:
        """Work out the settings for the active profile as its devices come and go."""
        desired, error = self._render()
        if not self.managed:
            self._changed.set()  # to check PHD2's equipment against the new devices
        elif desired != self._desired or error != self._desired_error:
            self._desired, self._desired_error = desired, error
            self._changed.set()

    def _render(self) -> tuple[Phd2Settings | None, str | None]:
        if not self.managed:
            return None, None
        profile = self._equipment.active_profile
        profile_id = self._equipment.active
        camera = self._equipment.ready_device(Role.GUIDE_CAMERA)
        mount = self._equipment.ready_device(Role.MOUNT)
        client = self._indi
        if profile is None or profile_id is None or client is None:
            return None, None
        if camera is None or mount is None:
            return None, None
        optics = profile.guiding_optics
        if optics is None:
            train = "imaging" if profile.guiding_through_imaging else "guiding"
            return None, f"the profile has no {train} optics: PHD2 needs the focal length"
        try:
            sensor = Camera(client, camera).sensor
            rig = GuideRig(
                camera=camera,
                mount=mount,
                pixel_size=sensor.pixel_size_x,
                focal_length=optics.focal_length * optics.reducer,
                guide_rate=Mount(client, mount).guide_rate,
                indi_host=self._indi_host,
                indi_port=self._indi_port,
            )
            return render(rig, profile_id), None
        except (DeviceError, KeyError, ValueError) as e:
            log.warning("cannot render PHD2 settings: %s", e)
            return None, f"cannot describe the guide camera to PHD2: {e}"

    def _on_event(self, event: Phd2Event) -> None:
        match event.name:
            case "Version":
                version = event.data.get("PHDVersion")
                self._store.set((*ROOT, "phd2", "version"), str(version) if version else None)
            case "AppState":
                state = event.data.get("State")
                if isinstance(state, str):
                    self._set_app_state(state)
            case name if name in _STATE_OF_EVENT:
                self._set_app_state(_STATE_OF_EVENT[name])
            case name if name in _QUERY_EVENTS:
                self._changed.set()  # _sync asks for the state
            case _:
                pass

    def _set_app_state(self, state: str, *, wake: bool = True) -> None:
        if state == self._app_state:
            return
        was_busy = self._app_state not in IDLE_STATES
        self._app_state = state
        self._store.set((*ROOT, "app_state"), state)
        if wake and was_busy and state in IDLE_STATES:
            self._changed.set()  # pending settings may go in now

    def _status(self) -> SettingsStatus:
        value = self._store.get((*ROOT, "settings"))
        return SettingsStatus(value) if isinstance(value, str) else SettingsStatus.NONE

    def _publish_settings(self, status: SettingsStatus, error: str | None = None) -> None:
        with self._store.transaction():
            self._store.set((*ROOT, "settings"), status.value)
            self._store.set((*ROOT, "error"), error)

    def _server(self, *, connected: bool, error: str | None = None) -> dict[str, Json]:
        return {
            "host": self._host,
            "port": self._port,
            "connected": connected,
            "version": None,
            "error": error,
        }

    def _publish_server(self, *, connected: bool, error: str | None = None) -> None:
        path = (*ROOT, "phd2")
        with self._store.transaction():
            self._store.set((*path, "connected"), connected)
            self._store.set((*path, "error"), error)
            if not connected:
                self._store.set((*path, "version"), None)


def _write_settings(path: FsPath, content: str) -> None:
    """Readable by PHD2's service, which may run as another user (a container)."""
    write_atomic(path, content)
    path.chmod(0o644)
