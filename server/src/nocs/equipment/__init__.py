"""Equipment profiles, device roles and the service that connects them."""

from nocs.equipment.ports import SerialPort, serial_ports
from nocs.equipment.profiles import (
    DeviceConfig,
    Optics,
    OutputConfig,
    Profile,
    ProfileError,
    ProfileStore,
    Role,
)
from nocs.equipment.service import (
    Connection,
    DeviceStatus,
    DriverRestartError,
    EquipmentBusyError,
    EquipmentService,
)

__all__ = [
    "Connection",
    "DeviceConfig",
    "DeviceStatus",
    "DriverRestartError",
    "EquipmentBusyError",
    "EquipmentService",
    "Optics",
    "OutputConfig",
    "Profile",
    "ProfileError",
    "ProfileStore",
    "Role",
    "SerialPort",
    "serial_ports",
]
