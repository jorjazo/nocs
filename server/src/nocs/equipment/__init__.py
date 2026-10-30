"""Equipment profiles, device roles and the service that connects them."""

from nocs.equipment.ports import SerialPort, serial_ports
from nocs.equipment.profiles import (
    DeviceConfig,
    Optics,
    Profile,
    ProfileError,
    ProfileStore,
    Role,
    Site,
)
from nocs.equipment.service import (
    Connection,
    DeviceStatus,
    EquipmentBusyError,
    EquipmentService,
)

__all__ = [
    "Connection",
    "DeviceConfig",
    "DeviceStatus",
    "EquipmentBusyError",
    "EquipmentService",
    "Optics",
    "Profile",
    "ProfileError",
    "ProfileStore",
    "Role",
    "SerialPort",
    "Site",
    "serial_ports",
]
