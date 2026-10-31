"""Connects the devices of an equipment profile and tracks the status of every role.

State layout under ``("equipment",)``::

    profiles:   {<id>: {name}}
    active:     id of the selected profile, or None
    connection: disconnected | connecting | connected | disconnecting
    error:      why the profile cannot be connected right now, or None
    devices:    {<role>: {driver, device, status, error}}

Connecting starts the drivers that are not running yet, waits for each device,
sets its serial port, connects it and waits until its facade is ready. Roles
connect independently: one failing device leaves the others usable, and
connecting the same profile again retries the ones that failed.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine
from enum import StrEnum
from typing import Any, Protocol

import anyio

from nocs.devices import Camera, Device, DeviceError, DeviceInterface, FilterWheel, Focuser, Mount
from nocs.devices.base import device_interfaces
from nocs.equipment.profiles import DeviceConfig, Profile, ProfileStore, Role
from nocs.indi import IndiClient, IndiEvent, PropertyDeleted, PropertyUpdated, TextElement
from nocs.indi.drivers import DriverControlError, DriverFifo
from nocs.state import Json, Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("equipment",)

DRIVER_START_TIMEOUT = 20.0
"""How long a driver may take to define its devices."""
DISCONNECT_TIMEOUT = 10.0
SETTLE_QUIET = 0.5
SETTLE_MAX = 5.0


class Connection(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"


class DeviceStatus(StrEnum):
    WAITING = "waiting"
    """The device is not defined yet (driver starting, or indiserver unreachable)."""
    CONNECTING = "connecting"
    READY = "ready"
    ERROR = "error"
    DISCONNECTED = "disconnected"


ROLE_INTERFACE: dict[Role, DeviceInterface | None] = {
    Role.MAIN_CAMERA: DeviceInterface.CCD,
    Role.GUIDE_CAMERA: DeviceInterface.CCD,
    Role.MOUNT: DeviceInterface.TELESCOPE,
    Role.FOCUSER: DeviceInterface.FOCUSER,
    Role.FILTER_WHEEL: DeviceInterface.FILTER,
    # Power boxes declare a mix of interfaces (AUX, weather, focuser…): any device
    # of the driver qualifies.
    Role.POWER_BOX: None,
}

ROLE_FACADE: dict[Role, type[Device]] = {
    Role.MAIN_CAMERA: Camera,
    Role.GUIDE_CAMERA: Camera,
    Role.MOUNT: Mount,
    Role.FOCUSER: Focuser,
    Role.FILTER_WHEEL: FilterWheel,
    Role.POWER_BOX: Device,
}


class IndiConnection(Protocol):
    """The live indiserver connection (``IndiBridge``)."""

    @property
    def client(self) -> IndiClient | None: ...

    def watch(self, watcher: Callable[[IndiClient | None], None]) -> Callable[[], None]: ...


class EquipmentBusyError(Exception):
    """The request conflicts with the profile currently connected."""


def driver_devices(client: IndiClient, driver: str) -> list[str]:
    """Devices defined by a driver executable, according to their ``DRIVER_INFO``."""
    names: list[str] = []
    for name in sorted(client.devices):
        info = client.get_property(name, "DRIVER_INFO")
        executable = info.elements.get("DRIVER_EXEC") if info is not None else None
        if isinstance(executable, TextElement) and executable.value == driver:
            names.append(name)
    return names


def candidates(client: IndiClient, role: Role, config: DeviceConfig) -> list[str]:
    """Devices that can play ``role`` for this configuration."""
    if config.device is not None:
        return [config.device] if config.device in client.devices else []
    interface = ROLE_INTERFACE[role]
    return [
        name
        for name in driver_devices(client, config.driver)
        if interface is None or interface in device_interfaces(client, name)
    ]


class EquipmentService:
    def __init__(
        self,
        store: StateStore,
        profiles: ProfileStore,
        bridge: IndiConnection,
        fifo: DriverFifo | None,
        *,
        driver_timeout: float = DRIVER_START_TIMEOUT,
    ) -> None:
        self._store = store
        self._profiles = profiles
        self._fifo = fifo
        self._driver_timeout = driver_timeout
        self._client: IndiClient | None = None
        self._settled: IndiClient | None = None
        self._remove_listener = lambda: None
        self._task: asyncio.Task[None] | None = None
        self._connection = Connection.DISCONNECTED
        self._profile_id = profiles.active
        self._profile = profiles.get(self._profile_id) if self._profile_id else None
        self._resolved: dict[Role, str] = {}
        self._started: set[str] = set()
        """Drivers NOCS started, and therefore stops on disconnect."""
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._status: dict[Role, DeviceStatus] = {}
        self._listeners: list[Callable[[], None]] = []

        with store.transaction():
            self._publish_profiles()
            store.set((*ROOT, "active"), self._profile_id)
            self._publish_connection(Connection.DISCONNECTED)
            self._publish_roles(DeviceStatus.DISCONNECTED)
        self._unwatch = bridge.watch(self._on_client)
        if bridge.client is not None:
            self._on_client(bridge.client)

    @property
    def connection(self) -> Connection:
        return self._connection

    @property
    def active(self) -> str | None:
        return self._profile_id

    @property
    def active_profile(self) -> Profile | None:
        return self._profile

    def ready_device(self, role: Role) -> str | None:
        """The INDI device playing ``role``, if it is connected and ready."""
        if self._status.get(role) is not DeviceStatus.READY:
            return None
        return self._resolved.get(role)

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call ``listener`` whenever the status of a role changes."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    # -- profiles ---------------------------------------------------------

    def profiles(self) -> dict[str, Profile]:
        return self._profiles.load_all()

    def profile(self, profile_id: str) -> Profile | None:
        return self._profiles.get(profile_id)

    def save_profile(self, profile_id: str, profile: Profile) -> None:
        """Create or replace a profile. Changes to the connected one apply on next connect."""
        self._profiles.put(profile_id, profile)
        self._publish_profiles()

    def delete_profile(self, profile_id: str) -> bool:
        if profile_id == self._profile_id:
            if self._connection is not Connection.DISCONNECTED:
                raise EquipmentBusyError(f"profile {profile_id} is in use: disconnect it first")
            self._select(None, None)
        deleted = self._profiles.delete(profile_id)
        self._publish_profiles()
        return deleted

    # -- connection -------------------------------------------------------

    def connect(self, profile_id: str) -> None:
        """Start connecting a profile; progress is published in the state.

        Connecting the profile that is already connected retries the roles that are
        not ready.
        """
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise KeyError(profile_id)
        if self._connection is not Connection.DISCONNECTED and profile_id != self._profile_id:
            raise EquipmentBusyError(f"disconnect {self._profile_id} first")
        if self._connection is Connection.DISCONNECTING:
            raise EquipmentBusyError(f"{profile_id} is disconnecting")
        if self._task is not None and not self._task.done():
            return  # already connecting
        self._select(profile_id, profile)
        self._spawn(self._connect())

    def disconnect(self) -> None:
        """Disconnect every device of the profile and stop the drivers NOCS started."""
        if self._connection in (Connection.DISCONNECTED, Connection.DISCONNECTING):
            return
        self._spawn(self._disconnect(self._task))

    async def close(self) -> None:
        """Stop working on the server's shutdown. Devices and drivers stay as they are."""
        self._unwatch()
        self._remove_listener()
        if self._task is not None:
            self._task.cancel()
            await asyncio.wait({self._task})

    # -- internals: passes ------------------------------------------------

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        self._task = asyncio.create_task(coro, name="equipment")

    async def _connect(self) -> None:
        profile = self._profile
        assert profile is not None
        self._publish_connection(Connection.CONNECTING)
        self._publish_roles(DeviceStatus.WAITING)
        client = self._client
        if client is None:
            # Resumed by _on_client when indiserver is back.
            self._publish_connection(Connection.CONNECTING, "waiting for indiserver")
            return
        try:
            await self._settle(client)
            pending = self._start_drivers(profile)
            async with anyio.create_task_group() as group:
                for role in pending:
                    group.start_soon(self._connect_role, client, role, profile.devices[role])
            await self._configure_cameras(client, profile)
        except Exception as e:
            log.exception("connecting %s failed", self._profile_id)
            self._publish_connection(Connection.CONNECTING, f"connecting failed: {e}")
            return
        self._publish_connection(Connection.CONNECTED)

    async def _disconnect(self, previous: asyncio.Task[None] | None) -> None:
        if previous is not None and not previous.done():
            previous.cancel()
            await asyncio.wait({previous})
        self._publish_connection(Connection.DISCONNECTING)
        client = self._client
        if client is not None:
            async with anyio.create_task_group() as group:
                for name in sorted(set(self._resolved.values())):
                    group.start_soon(self._disconnect_device, client, name)
        if self._fifo is not None:
            for driver in sorted(self._started):
                try:
                    self._fifo.stop(driver)
                except DriverControlError as e:
                    log.warning("cannot stop driver %s: %s", driver, e)
        self._started.clear()
        self._resolved.clear()
        self._publish_roles(DeviceStatus.DISCONNECTED)
        self._publish_connection(Connection.DISCONNECTED)

    async def _disconnect_device(self, client: IndiClient, name: str) -> None:
        if name not in client.devices:
            return
        try:
            await Device(client, name).disconnect(DISCONNECT_TIMEOUT)
        except DeviceError as e:
            log.warning("cannot disconnect %s: %s", name, e)

    async def _settle(self, client: IndiClient) -> None:
        """After connecting to indiserver, wait until running drivers have defined their devices.

        Starting a driver whose devices are merely late would run it twice, so the
        first pass on a new connection waits for the definitions to stop arriving.
        """
        if self._settled is client:
            return

        def size() -> int:
            return sum(len(properties) for properties in client.devices.values())

        loop = asyncio.get_running_loop()
        deadline = loop.time() + SETTLE_MAX
        last, quiet_since = size(), loop.time()
        while loop.time() < deadline and loop.time() - quiet_since < SETTLE_QUIET:
            await anyio.sleep(0.1)
            if (current := size()) != last:
                last, quiet_since = current, loop.time()
        self._settled = client

    def _start_drivers(self, profile: Profile) -> list[Role]:
        """Start the drivers whose devices are missing; returns the roles worth connecting."""
        client = self._client
        assert client is not None
        roles_by_driver: defaultdict[str, list[Role]] = defaultdict(list)
        for role, config in profile.devices.items():
            roles_by_driver[config.driver].append(role)
        pending: list[Role] = []
        for driver, roles in roles_by_driver.items():
            running = driver_devices(client, driver) or any(
                candidates(client, role, profile.devices[role]) for role in roles
            )
            if running:
                pending += roles
                continue
            try:
                if self._fifo is None:
                    raise DriverControlError(
                        f"driver {driver} is not running and indiserver has no driver FIFO"
                    )
                self._fifo.start(driver)
            except DriverControlError as e:
                for role in roles:
                    self._publish_role(role, status=DeviceStatus.ERROR, error=str(e))
                continue
            self._started.add(driver)
            pending += roles
        return pending

    async def _connect_role(self, client: IndiClient, role: Role, config: DeviceConfig) -> None:
        try:
            name = await self._resolve(client, role, config)
            self._resolved[role] = name
            self._publish_role(role, device=name, status=DeviceStatus.CONNECTING)
            facade = ROLE_FACADE[role](client, name)
            # Roles can share a device (a camera with a built-in filter wheel).
            async with self._locks[name]:
                if config.port is not None and not facade.connected and facade.has("DEVICE_PORT"):
                    await facade.command("DEVICE_PORT", {"PORT": config.port})
                await facade.connect()
        except (DeviceError, ConnectionError, KeyError, ValueError) as e:
            self._publish_role(role, status=DeviceStatus.ERROR, error=str(e))
        else:
            self._publish_role(role, status=DeviceStatus.READY)

    async def _configure_cameras(self, client: IndiClient, profile: Profile) -> None:
        """Point the cameras at the rig's other devices and optics, for their FITS headers.

        The guide camera is also left sending BLOBs.
        """

        def name(role: Role) -> str:
            return self.ready_device(role) or ""

        cameras = [
            (Role.MAIN_CAMERA, name(Role.FILTER_WHEEL), name(Role.FOCUSER), profile.imaging),
            (Role.GUIDE_CAMERA, "", "", profile.guiding),
        ]
        for role, filter_wheel, focuser, optics in cameras:
            device = self.ready_device(role)
            if device is None:
                continue
            camera = Camera(client, device)
            try:
                await camera.set_snooped_devices(
                    mount=name(Role.MOUNT), focuser=focuser, filter_wheel=filter_wheel
                )
                if optics is not None:
                    await camera.set_optics(optics.focal_length * optics.reducer, optics.aperture)
                if role is Role.GUIDE_CAMERA:
                    # Its frames go to PHD2 as BLOBs too, which UPLOAD_LOCAL would stop
                    # (ADR 0012), whoever set it: undo it before anyone guides.
                    await camera.set_upload_mode("UPLOAD_CLIENT")
            except (DeviceError, ConnectionError, KeyError) as e:
                log.warning("cannot configure %s (%s): %s", role.value, device, e)

    async def _resolve(self, client: IndiClient, role: Role, config: DeviceConfig) -> str:
        try:
            await client.wait_for(lambda c: bool(candidates(c, role, config)), self._driver_timeout)
        except TimeoutError:
            raise DeviceError(self._not_found(client, config)) from None
        if config.device is not None:
            return config.device
        # A driver with several devices (all ZWO cameras) defines them one after another.
        await anyio.sleep(SETTLE_QUIET)
        found = candidates(client, role, config)
        if len(found) > 1:
            raise DeviceError(f"{config.driver} has several devices, choose one: {found}")
        if not found:
            raise DeviceError(self._not_found(client, config))
        return found[0]

    def _not_found(self, client: IndiClient, config: DeviceConfig) -> str:
        defined = driver_devices(client, config.driver)
        if defined:
            wanted = config.device or "a suitable device"
            return f"{config.driver} does not define {wanted}; it defines {defined}"
        if config.driver in self._started and self._fifo is not None:
            # indiserver keeps restarting a driver that cannot run; stop it.
            self._started.discard(config.driver)
            try:
                self._fifo.stop(config.driver)
            except DriverControlError as e:
                log.warning("cannot stop driver %s: %s", config.driver, e)
        return (
            f"{config.driver} defined no device within {self._driver_timeout:g} s "
            "(is the driver installed and the device plugged in?)"
        )

    # -- internals: indiserver connection ---------------------------------

    def _on_client(self, client: IndiClient | None) -> None:
        self._remove_listener()
        self._remove_listener = lambda: None
        self._client = client
        if client is None:
            if self._connection in (Connection.CONNECTING, Connection.CONNECTED):
                if self._task is not None:
                    self._task.cancel()
                self._publish_connection(Connection.CONNECTING, "lost connection to indiserver")
                self._publish_roles(DeviceStatus.WAITING)
            return
        self._remove_listener = client.add_listener(self._on_event)
        if self._connection in (Connection.CONNECTING, Connection.CONNECTED):
            self._spawn(self._connect())

    def _on_event(self, event: IndiEvent) -> None:
        """Notice devices that go away or are disconnected outside NOCS."""
        if self._connection is not Connection.CONNECTED:
            return
        match event:
            case PropertyDeleted(device=device, name=None):
                for role in self._roles_of(device):
                    self._publish_role(
                        role, status=DeviceStatus.ERROR, error=f"{device} disappeared"
                    )
            case PropertyUpdated(property=prop) if prop.name == "CONNECTION":
                if not prop.switch("CONNECT"):
                    for role in self._roles_of(prop.device):
                        self._publish_role(role, status=DeviceStatus.DISCONNECTED)
            case _:
                pass

    def _roles_of(self, device: str) -> list[Role]:
        return [role for role, name in self._resolved.items() if name == device]

    # -- internals: state -------------------------------------------------

    def _select(self, profile_id: str | None, profile: Profile | None) -> None:
        if profile_id == self._profile_id and profile == self._profile:
            return
        self._profile_id, self._profile = profile_id, profile
        self._profiles.active = profile_id
        self._resolved.clear()
        with self._store.transaction():
            self._store.set((*ROOT, "active"), profile_id)
            self._publish_roles(DeviceStatus.DISCONNECTED)

    def _publish_profiles(self) -> None:
        summary: dict[str, Json] = {
            profile_id: {"name": profile.name}
            for profile_id, profile in self._profiles.load_all().items()
        }
        self._store.set((*ROOT, "profiles"), summary)

    def _publish_connection(self, connection: Connection, error: str | None = None) -> None:
        self._connection = connection
        with self._store.transaction():
            self._store.set((*ROOT, "connection"), connection.value)
            self._store.set((*ROOT, "error"), error)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:
                log.exception("equipment listener failed")

    def _publish_roles(self, status: DeviceStatus) -> None:
        roles: dict[str, Json] = {}
        self._status = {}
        if self._profile is not None:
            for role, config in self._profile.devices.items():
                self._status[role] = status
                roles[role.value] = {
                    "driver": config.driver,
                    "device": self._resolved.get(role, config.device),
                    "status": status.value,
                    "error": None,
                }
        self._store.set((*ROOT, "devices"), roles)
        self._notify()

    def _publish_role(
        self,
        role: Role,
        *,
        status: DeviceStatus,
        device: str | None = None,
        error: str | None = None,
    ) -> None:
        path = (*ROOT, "devices", role.value)
        with self._store.transaction():
            if device is not None:
                self._store.set((*path, "device"), device)
            self._store.set((*path, "status"), status.value)
            self._store.set((*path, "error"), error)
        self._status[role] = status
        self._notify()
