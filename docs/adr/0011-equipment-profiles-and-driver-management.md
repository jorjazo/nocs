# 0011. Equipment profiles and indiserver driver management

Date: 2026-10-30 · Status: Accepted

## Context

Phase 2 replaces the laptop at the telescope. The user picks a rig ("AM5 +
2600MC portable") and NOCS must start the right INDI drivers, connect the
devices and know which device plays which role (main camera, guide camera,
mount…). Facts that shape the decision:

- One INDI driver can expose several devices: `indi_asi_ccd` serves every ZWO
  camera on the bus, so the main and the guide camera come from the same
  driver. A role must point at a **device**, not at a driver.
- `indiserver -f <fifo>` starts and stops drivers at runtime (`start <driver>
  [-n "<name>"]`, `stop <driver> [-n "<name>"]`). It needs no driver on the
  command line, but it does not create the FIFO, and it restarts a driver that
  cannot be executed up to `-r` times instead of reporting an error.
- `DRIVER_INFO.DRIVER_EXEC` tells which executable defined a device, so
  devices already running (started by the user, or by the dev container) can be
  recognised and adopted.
- Drivers list themselves in `/usr/share/indi/*.xml` (`drivers.xml` and one
  file per third-party package): a ready-made catalog.
- Serial devices (AM5, PPBA) are configured through `DEVICE_PORT`; the stable
  name of a USB serial adapter is its `/dev/serial/by-id/` link, not
  `/dev/ttyACM0`.

Options considered for who runs indiserver:

1. **nocsd spawns indiserver** as a child process and supervises it. One less
   unit to install, but nocsd then owns process supervision, log handling and
   restarts, and development (indiserver in a container) takes a different
   path from production.
2. **indiserver runs as its own service** (a systemd unit in production, a
   container in development and CI), always with a FIFO; nocsd talks to it over
   TCP and the FIFO only. One code path everywhere; systemd restarts and logs
   it; a crash of nocsd does not take the drivers (and a running exposure)
   down with it.
3. **Restart indiserver with a new driver list** on every profile change.
   Simple, but it drops every device to change one.

## Decision

- **indiserver is an external service with a driver FIFO** (option 2). nocsd
  connects to it over TCP (`NOCS_INDI_HOST`/`NOCS_INDI_PORT`) and writes driver
  commands to the FIFO (`NOCS_INDI_FIFO`). Without a FIFO nocsd still works,
  but can only adopt drivers that are already running.
- **Equipment profiles** are JSON files, one per profile, in the configuration
  directory (`NOCS_CONFIG_DIR`, default `~/.config/nocs/profiles/`), validated
  by Pydantic models. Files make export, backup and hand editing trivial; the
  catalog of frames is a different concern (see the storage ADR).
- A profile maps **roles** (`main_camera`, `guide_camera`, `mount`, `focuser`,
  `filter_wheel`, `power_box`) to a driver executable, an optional INDI device
  name and an optional serial port. When the name is omitted, the device is
  resolved among those its driver defined, by the role's interface; an
  ambiguous match is an error that asks for a name. The profile also holds the
  imaging and guiding optics and the site.
- **Connecting a profile** starts only the drivers whose devices are not
  already present, waits for each device, sets `DEVICE_PORT` when configured,
  connects it and waits until its facade is ready. Devices connect
  independently: one failing device does not stop the others. **Disconnecting**
  stops only the drivers NOCS started. The active profile and the status of
  every role are part of the state tree (`equipment`).
- A driver that does not define its device in time is reported as an error and
  stopped through the FIFO, so indiserver does not keep restarting it.
- The **driver catalog** is read from the INDI XML files
  (`NOCS_INDI_DRIVERS_DIR`, default `/usr/share/indi`); a driver missing from
  it can still be named explicitly.

## Consequences

- Development, CI and the Pi use the same mechanism. The dev container creates
  the FIFO (and exposes the driver catalog) in a directory shared with the
  host.
- Packaging (phase 6) ships an `indiserver` systemd unit, and nocsd's user must
  be able to write its FIFO. systemd restarts indiserver when it exits; an
  indiserver or driver that hangs without exiting is not detected yet, and is
  left to be designed in phase 6.
- Profiles reference device names, which are stable for most drivers (ZWO
  includes the camera model in the name). Two identical cameras on one driver
  would need a further rule (e.g. by serial number) when it happens.
- The state shows the status of each role, which the Rig screen and the
  "connect" step of the Tonight checklist will render directly.
