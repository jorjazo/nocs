"""Connects the devices of an equipment profile and tracks the status of every role.

State layout under ``("equipment",)``::

    profiles:   {<id>: {name}}
    active:     id of the selected profile, or None
    connection: disconnected | connecting | connected | disconnecting
    error:      why the profile cannot be connected right now, or None
    devices:    {<role>: {driver, device, status, error, unresponsive_since}}
    detecting:  {device, port, attempt, attempts} while a serial port is being looked
                for (ADR 0048), else None

Connecting starts the drivers that are not running yet, waits for each device,
sets its serial port, connects it and waits until its facade is ready. A serial
device without a port in the profile, or whose port is no longer plugged in, gets
one found by trying the ports one by one, and the profile keeps it (ADR 0048). Roles
connect independently: one failing device leaves the others usable, and
connecting the same profile again retries the ones that failed. A ready device that
stops answering a command (``nocs.devices.on_unresponsive``) makes its roles
``unresponsive`` until it sends anything again or its driver restarts (ADR 0030).
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from collections.abc import Callable, Collection, Coroutine
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

import anyio

from nocs.devices import (
    Camera,
    Device,
    DeviceError,
    DeviceInterface,
    FilterWheel,
    Focuser,
    Mount,
    PowerBox,
    WeatherSensor,
    on_unresponsive,
)
from nocs.devices.base import device_interfaces, event_device
from nocs.equipment.detect import connect as connect_serial
from nocs.equipment.detect import find_port, set_port, uses_serial
from nocs.equipment.ports import (
    BY_ID,
    SerialPort,
    ranked,
    real_path,
    serial_ports,
    stable_name,
    words,
)
from nocs.equipment.profiles import DeviceConfig, Profile, ProfileStore, Role
from nocs.indi import IndiClient, IndiEvent, PropertyDeleted, PropertyUpdated, TextElement
from nocs.indi.drivers import DriverControlError, DriverFifo
from nocs.state import Json, Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("equipment",)

DRIVER_START_TIMEOUT = 20.0
DRIVER_STOP_TIMEOUT = 10.0
"""Seconds for indiserver to remove a stopped driver's devices."""
"""How long a driver may take to define its devices."""
DISCONNECT_TIMEOUT = 10.0
SETTLE_QUIET = 0.5
LIST_TIMEOUT = 10.0
"""How long a driver started only to list its devices may take to define one."""
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
    UNRESPONSIVE = "unresponsive"
    """Connected, but it stopped answering (ADR 0030): restart its driver."""


ROLE_INTERFACE: dict[Role, DeviceInterface] = {
    Role.MAIN_CAMERA: DeviceInterface.CCD,
    Role.GUIDE_CAMERA: DeviceInterface.CCD,
    Role.MOUNT: DeviceInterface.TELESCOPE,
    Role.FOCUSER: DeviceInterface.FOCUSER,
    Role.FILTER_WHEEL: DeviceInterface.FILTER,
    # One device may play several of these (a power box: power, weather, focuser).
    Role.POWER: DeviceInterface.POWER,
    Role.WEATHER: DeviceInterface.WEATHER,
}

SERIAL_ROLES = frozenset({Role.MOUNT, Role.FOCUSER, Role.FILTER_WHEEL, Role.POWER, Role.WEATHER})
"""Roles whose devices can be on a serial port: cameras are USB devices of their own."""

ROLE_FACADE: dict[Role, type[Device]] = {
    Role.MAIN_CAMERA: Camera,
    Role.GUIDE_CAMERA: Camera,
    Role.MOUNT: Mount,
    Role.FOCUSER: Focuser,
    Role.FILTER_WHEEL: FilterWheel,
    Role.POWER: PowerBox,
    Role.WEATHER: WeatherSensor,
}


class IndiConnection(Protocol):
    """The live indiserver connection (``IndiBridge``)."""

    @property
    def client(self) -> IndiClient | None: ...

    def watch(self, watcher: Callable[[IndiClient | None], None]) -> Callable[[], None]: ...


class EquipmentBusyError(Exception):
    """The request conflicts with the profile currently connected."""


class DriverRestartError(Exception):
    """A role's driver could not be restarted, or its roles did not come back."""


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
        if interface in device_interfaces(client, name)
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
        ports: Callable[[], list[SerialPort]] = serial_ports,
        reserved_ports: Callable[[], Collection[str]] = tuple,
    ) -> None:
        """``ports`` lists the serial ports to look for devices on; ``reserved_ports``
        says which ones something else holds (gpsd's GPS)."""
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
        self._restarting: set[str] = set()
        """Devices whose driver is being restarted: their going away is expected."""
        self._listing: dict[str, int] = {}
        """Drivers started only for a question (their devices, a port), by how many
        questions hold them: stopped after the last unless a connect needs them."""
        self._ports = ports
        self._reserved_ports = reserved_ports
        self._detecting = asyncio.Lock()
        """One port search at a time: two would open each other's ports."""
        self._saving = asyncio.Lock()
        self._searching: set[str] = set()
        """Devices whose port is being looked for: their refused connections are expected."""

        with store.transaction():
            self._publish_profiles()
            store.set((*ROOT, "active"), self._profile_id)
            self._publish_connection(Connection.DISCONNECTED)
            self._publish_roles(DeviceStatus.DISCONNECTED)
            store.set((*ROOT, "detecting"), None)
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

    async def restart_driver(self, role: Role) -> None:
        """Stop the driver of ``role`` and start it again, then connect every role it
        serves (ADR 0030): the first step against a device that stopped answering.

        indiserver kills a stopped driver, hung or not. Raises ``DriverRestartError``
        when it cannot be done or a role does not come back ready.
        """
        profile, client = self._profile, self._client
        if self._connection is not Connection.CONNECTED or profile is None or client is None:
            raise DriverRestartError("the profile is not connected")
        if role not in profile.devices:
            raise DriverRestartError(f"the profile has no {role.value}")
        if self._fifo is None:
            raise DriverRestartError("indiserver has no driver FIFO")
        driver = profile.devices[role].driver
        if driver in self._restarting:
            raise DriverRestartError(f"{driver} is already being restarted")
        roles = [r for r, config in profile.devices.items() if config.driver == driver]
        names = {self._resolved[r] for r in roles if r in self._resolved}
        names.update(driver_devices(client, driver))
        log.warning("restarting %s for the %s", driver, role.value)
        self._restarting.add(driver)
        self._restarting.update(names)
        try:
            for r in roles:
                self._publish_role(r, status=DeviceStatus.WAITING)
            try:
                self._fifo.stop(driver)
                await client.wait_for(lambda c: not names & c.devices.keys(), DRIVER_STOP_TIMEOUT)
                self._fifo.start(driver)
            except (DriverControlError, TimeoutError) as e:
                error = str(e) or f"{driver} did not stop"
                for r in roles:
                    self._publish_role(r, status=DeviceStatus.ERROR, error=error)
                raise DriverRestartError(f"cannot restart {driver}: {error}") from e
            # Whether disconnecting stops it stays as it was: a driver NOCS found
            # running keeps running.
            for r in roles:
                self._resolved.pop(r, None)
            async with anyio.create_task_group() as group:
                for r in roles:
                    group.start_soon(self._connect_role, client, r, profile.devices[r])
            if Role.MAIN_CAMERA in roles or Role.GUIDE_CAMERA in roles:
                await self._configure_cameras(client, profile)
        finally:
            self._restarting.discard(driver)
            self._restarting.difference_update(names)
        failed = [r.value for r in roles if self._status.get(r) is not DeviceStatus.READY]
        if failed:
            raise DriverRestartError(f"{driver} restarted, but not ready: {', '.join(failed)}")

    async def list_devices(self, driver: str, role: Role) -> list[str]:
        """The devices ``driver`` defines that can play ``role``, for the profile editor.

        A driver that does not run is started for the question and stopped after (unless
        a profile connecting meanwhile needs it); drivers define their devices before
        they connect. USB drivers define only the devices plugged in.
        """
        client = self._client
        if client is None:
            raise ConnectionError("not connected to indiserver")
        config = DeviceConfig(driver=driver)
        if driver_devices(client, driver) and driver not in self._listing:
            return candidates(client, role, config)
        held = self._hold(driver)
        try:
            await client.wait_for(lambda c: bool(driver_devices(c, driver)), LIST_TIMEOUT)
            # A driver with several devices (all ZWO cameras) defines them one after another.
            await anyio.sleep(SETTLE_QUIET)
            return candidates(client, role, config)
        finally:
            if held:
                self._release(driver)

    async def detect_port(
        self, driver: str, role: Role, device: str | None = None, exclude: Collection[str] = ()
    ) -> str:
        """The serial port ``driver``'s device for ``role`` answers on, for the profile
        editor (ADR 0048): its by-id name when it has one.

        A connected device says which port it uses; any other is tried on each port
        but those in ``exclude`` (the profile's other devices'), and left disconnected
        after. A driver that does not run is started for the question and stopped after,
        as for ``list_devices``. Raises ``DeviceError`` (``PortNotFoundError`` when no
        port works).
        """
        client = self._client
        if client is None:
            raise ConnectionError("not connected to indiserver")
        if role not in SERIAL_ROLES:
            raise DeviceError(f"a {role.value.replace('_', ' ')} does not use a serial port")
        config = DeviceConfig(driver=driver, device=device)
        held = self._hold(driver)
        try:
            name = await self._resolve(client, role, config)
            facade = Device(client, name)
            async with self._locks[name]:
                await self._wait_defined(client, name)
                if not uses_serial(facade):
                    raise DeviceError(f"{name} does not use a serial port")
                if facade.connected:
                    return stable_name(facade.prop("DEVICE_PORT").text("PORT"), self._ports())
                port = await self._find_port(client, name, config, exclude=exclude)
                try:
                    await facade.disconnect()
                except DeviceError as e:
                    log.warning("cannot disconnect %s after finding its port: %s", name, e)
                return port
        finally:
            if held:
                self._release(driver)

    def _hold(self, driver: str) -> bool:
        """Start a driver for a question (its devices, a port) unless it runs for a
        connect or by itself; returns whether the question holds it, to ``_release``."""
        client = self._client
        assert client is not None
        if driver not in self._listing and (
            driver in self._started or driver_devices(client, driver)
        ):
            return False
        if driver not in self._listing:
            if self._fifo is None:
                raise DriverControlError(
                    f"driver {driver} is not running and indiserver has no FIFO"
                )
            self._fifo.start(driver)
        self._listing[driver] = self._listing.get(driver, 0) + 1
        return True

    def _release(self, driver: str) -> None:
        """Let go of a driver held for a question: stopped after the last one, unless a
        connect took it meanwhile."""
        left = self._listing.get(driver, 1) - 1
        if left > 0:
            self._listing[driver] = left
            return
        self._listing.pop(driver, None)
        if driver not in self._started and self._fifo is not None:
            try:
                self._fifo.stop(driver)
            except DriverControlError as e:
                log.warning("cannot stop driver %s: %s", driver, e)

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
            if driver in self._listing:  # started to list its devices: now it stays
                self._started.add(driver)
                pending += roles
                continue
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
                if not facade.connected:
                    await self._point_at_port(client, role, name, config)
                await facade.connect()
        except (DeviceError, ConnectionError, KeyError, ValueError) as e:
            self._publish_role(role, status=DeviceStatus.ERROR, error=str(e))
        else:
            self._publish_role(role, status=DeviceStatus.READY)

    async def _point_at_port(
        self, client: IndiClient, role: Role, name: str, config: DeviceConfig
    ) -> None:
        """Give a serial device its port before it connects: the profile's, or one found
        by trying them and then kept in the profile (ADR 0048). Leaves it connected when
        it had to look."""
        await self._wait_defined(client, name)
        facade = Device(client, name)
        if not facade.has("DEVICE_PORT"):
            return
        port = config.port
        if port is not None and not self._unplugged(port):
            await set_port(facade, port)
            if uses_serial(facade):
                await connect_serial(facade)
            return
        if role not in SERIAL_ROLES or not uses_serial(facade):
            return  # a camera, over the network, or a simulator
        profile = self._profile
        exclude: list[str] = []
        others: list[frozenset[str]] = []
        if profile is not None:
            for other_role, other in profile.devices.items():
                if self._same_device(other_role, other, config.driver, name):
                    continue
                if other.port is not None:
                    exclude.append(other.port)
                if other_role in SERIAL_ROLES:
                    others.append(words(other.device, other.model, other.driver))
        if port is not None:
            log.info("%s's port %s is not plugged in: looking for it", name, port)
        found = await self._find_port(client, name, config, exclude=exclude, others=others)
        await self._keep_port(config.driver, name, found)

    def _unplugged(self, port: str) -> bool:
        """Whether a stable port name is gone: the device came back on another adapter."""
        return port.startswith(f"{BY_ID}/") and not any(p.path == port for p in self._ports())

    def _same_device(self, role: Role, config: DeviceConfig, driver: str, name: str) -> bool:
        """Whether ``role`` is played by the device ``name`` (a power box's weather too)."""
        if config.driver != driver:
            return False
        return self._resolved.get(role, config.device) in (name, None)

    async def _wait_defined(self, client: IndiClient, name: str) -> None:
        """Wait for a device's ``CONNECTION``, and the rest of its definitions with it."""
        if client.get_property(name, "CONNECTION") is None:
            try:
                await client.wait_for_property(name, "CONNECTION", self._driver_timeout)
            except TimeoutError:
                raise DeviceError(f"device {name} not found") from None
            await self._quiet(client, name)

    async def _quiet(self, client: IndiClient, name: str) -> None:
        """Wait until a device just defined stops defining properties (``DEVICE_AUTO_SEARCH``
        comes after ``DEVICE_PORT``), at most ``SETTLE_MAX`` seconds."""

        def size() -> int:
            return len(client.devices.get(name, {}))

        loop = asyncio.get_running_loop()
        deadline = loop.time() + SETTLE_MAX
        last, quiet_since = size(), loop.time()
        while loop.time() < deadline and loop.time() - quiet_since < SETTLE_QUIET:
            await anyio.sleep(SETTLE_QUIET / 10)
            if (current := size()) != last:
                last, quiet_since = current, loop.time()

    async def _find_port(
        self,
        client: IndiClient,
        name: str,
        config: DeviceConfig,
        *,
        exclude: Collection[str] = (),
        others: list[frozenset[str]] | None = None,
    ) -> str:
        """Try the serial ports for device ``name`` until it connects on one (ADR 0048)."""
        async with self._detecting:
            available = self._ports()
            taken = [*exclude, *self._reserved_ports(), *self._ports_in_use(client, name)]
            own = words(name, config.model, config.driver)
            ports = [port.path for port in ranked(available, own, others or [], exclude=taken)]
            remembered = self._remembered_port(client, name, available, taken)
            if remembered is not None:
                ports.append(remembered)
            log.info("looking for %s on %s", name, ", ".join(ports) or "no serial port")

            def progress(port: str, attempt: int, attempts: int) -> None:
                detecting: Json = {
                    "device": name,
                    "port": port,
                    "attempt": attempt,
                    "attempts": attempts,
                }
                self._store.set((*ROOT, "detecting"), detecting)

            self._searching.add(name)
            try:
                return await find_port(
                    Device(client, name),
                    ports,
                    restart=lambda: self._restart_for_port(client, config.driver, name),
                    progress=progress,
                )
            finally:
                self._searching.discard(name)
                self._store.set((*ROOT, "detecting"), None)

    def _ports_in_use(self, client: IndiClient, name: str) -> list[str]:
        """The ports of the other serial devices connected on the server (not those over
        the network, or simulators: their port is only a setting)."""
        used: list[str] = []
        for device in client.devices:
            other = Device(client, device)
            if device == name or not other.connected or not uses_serial(other):
                continue
            port = other.prop("DEVICE_PORT")
            if "PORT" in port.elements:
                used.append(port.text("PORT"))
        return used

    def _remembered_port(
        self, client: IndiClient, name: str, available: list[SerialPort], taken: Collection[str]
    ) -> str | None:
        """The port a driver saved, when it is none of the USB adapters' (a Pi's own
        UART): tried last."""
        prop = client.get_property(name, "DEVICE_PORT")
        if prop is None or "PORT" not in prop.elements:
            return None
        port = prop.text("PORT").strip()
        node = real_path(port)
        if not port or any(p.device == node for p in available):
            return None
        if port in taken or node in {real_path(t) for t in taken}:
            return None
        return port if os.path.exists(node) else None

    async def _restart_for_port(self, client: IndiClient, driver: str, name: str) -> None:
        """Restart a driver that stopped answering on a wrong port, for the next one."""
        if self._fifo is None:
            raise DeviceError(
                f"{name} stopped answering on a serial port, and indiserver has no driver "
                "FIFO to restart it"
            )
        fifo = self._fifo
        added = name not in self._restarting  # restart_driver's own, else
        self._restarting.add(name)
        stopped = started = False
        try:
            fifo.stop(driver)
            stopped = True
            await client.wait_for(lambda c: name not in c.devices, DRIVER_STOP_TIMEOUT)
            fifo.start(driver)
            started = True
            await client.wait_for_property(name, "CONNECTION", self._driver_timeout)
            await self._quiet(client, name)
        except (DriverControlError, TimeoutError) as e:
            raise DeviceError(f"cannot restart {driver}: {e or 'it did not come back'}") from e
        finally:
            if stopped and not started:
                # Cancelled in between: a driver that ran before runs again.
                try:
                    fifo.start(driver)
                except DriverControlError as e:
                    log.warning("cannot start driver %s again: %s", driver, e)
            if added:
                self._restarting.discard(name)

    async def _keep_port(self, driver: str, name: str, port: str) -> None:
        """Save a port found for device ``name`` in the active profile, for every role
        it plays."""
        profile_id = self._profile_id
        if profile_id is None:
            return

        def patch(profile: Profile) -> Profile:
            devices = {
                role: config.model_copy(update={"port": port})
                if self._same_device(role, config, driver, name)
                else config
                for role, config in profile.devices.items()
            }
            return profile.model_copy(update={"devices": devices})

        def save() -> None:
            # What is on disk, which the owner may have edited since connecting.
            saved = self._profiles.get(profile_id)
            if saved is not None:
                self._profiles.put(profile_id, patch(saved))

        # Ports found at once for two devices: each saved on top of the other.
        async with self._saving:
            if self._profile is not None:
                self._profile = patch(self._profile)
            await anyio.to_thread.run_sync(save)
        log.info("%s is on %s: kept in profile %s", name, port, profile_id)

    async def _configure_cameras(self, client: IndiClient, profile: Profile) -> None:
        """Point the cameras at the rig's other devices and optics, for their FITS headers.

        The guide camera is also left sending BLOBs.
        """

        def name(role: Role) -> str:
            return self.ready_device(role) or ""

        cameras = [
            (Role.MAIN_CAMERA, name(Role.FILTER_WHEEL), name(Role.FOCUSER), profile.imaging),
            (Role.GUIDE_CAMERA, "", "", profile.guiding_optics),
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
        remove_events = client.add_listener(self._on_event)
        remove_unresponsive = on_unresponsive(client, self._on_unresponsive)

        def remove() -> None:
            remove_events()
            remove_unresponsive()

        self._remove_listener = remove
        if self._connection in (Connection.CONNECTING, Connection.CONNECTED):
            self._spawn(self._connect())

    def _on_event(self, event: IndiEvent) -> None:
        """Notice devices that go away, are disconnected outside NOCS, or answer again."""
        if self._connection is not Connection.CONNECTED:
            return
        device = None if isinstance(event, PropertyDeleted) else event_device(event)
        if device is not None:
            for role in self._roles_of(device):
                if self._status.get(role) is DeviceStatus.UNRESPONSIVE:
                    log.info("%s answers again", device)
                    self._publish_role(role, status=DeviceStatus.READY)
        match event:
            case PropertyDeleted(device=device, name=None) if device not in self._restarting:
                for role in self._roles_of(device):
                    self._publish_role(
                        role, status=DeviceStatus.ERROR, error=f"{device} disappeared"
                    )
            case PropertyUpdated(property=prop) if (
                prop.name == "CONNECTION" and prop.device not in self._searching
            ):
                if not prop.switch("CONNECT"):
                    for role in self._roles_of(prop.device):
                        self._publish_role(role, status=DeviceStatus.DISCONNECTED)
            case _:
                pass

    def _on_unresponsive(self, device: str, reason: str) -> None:
        if self._connection is not Connection.CONNECTED or device in self._restarting:
            return
        for role in self._roles_of(device):
            if self._status.get(role) is DeviceStatus.READY:
                self._publish_role(role, status=DeviceStatus.UNRESPONSIVE, error=reason)

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
            profile_id: {"name": profile.name, "solve_exposure": profile.solving.exposure}
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
                    "unresponsive_since": None,
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
            since = (
                datetime.now(UTC).isoformat(timespec="seconds")
                if status is DeviceStatus.UNRESPONSIVE
                else None
            )
            self._store.set((*path, "unresponsive_since"), since)
        self._status[role] = status
        self._notify()
