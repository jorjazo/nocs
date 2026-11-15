# 0048. Serial ports are found by trying them, and the profile keeps the one that works

Date: 2026-11-15 · Status: Proposed

## Context

On the lab rig, connecting the ZWO AM5 and the Pegasus PPBA failed again and again
("ZWO AM5 is not answering"). The profile named no serial port for either, so each
driver used the port it had saved itself, or its factory default when it had none.
Facts:

- **Both drivers default to the same port**: `indi_lx200am5` and `indi_pegasus_ppba`
  start on `/dev/ttyUSB0` with their own port search (`DEVICE_AUTO_SEARCH`) on. On the
  lab Pi `/dev/ttyUSB0` is the PPBA's FTDI adapter, the AM5 is `/dev/ttyACM0` and the
  USB GPS `/dev/ttyACM1` (gpsd's).
- **The AM5's driver never comes back from the PPBA's port.** It opened
  `/dev/ttyUSB0` and waited in a blocking `read()` forever: it answered nothing, not
  even indiserver's `getProperties`, and the PPBA could not have its port. Only
  stopping the driver ended it.
- **A driver's saved port lives in its config file**, in `$HOME/.indi` of the user
  indiserver runs as. A new box has none; on the lab, moving the services from the
  user `nocsd` to `nocs` (another home) lost them, and the failures came back. The
  same happened on the box's first night (2026-11-12) until someone set the ports by
  hand.
- **Setting a port means knowing what a serial port is.** The profile editor offered
  the stable names of `/dev/serial/by-id/`, which most owners will not understand.
- **The driver is the test.** With a port set and its own search off, a driver that
  finds its device there connects (`Ok`); on another device's port its handshake
  fails (`Alert`) or it hangs. On the lab, with its search off, the AM5's driver
  refused the PPBA's port after 10 s instead of hanging; the PPBA's refuses a port
  without its device in 2 s, and both connect on their own in well under a second.
  A hung driver is noticed by the probe of ADR 0030 and ends when indiserver stops it.
- **A device can answer another driver's handshake late.** Right after the AM5's
  driver had tried the PPBA's port, the PPBA's own driver failed there in 20 ms (it
  read what the PPBA answered the AM5's queries); its second try worked.
- **Stable names say who made most adapters**: `usb-ZWO_Systems_ZWO_Device_…`,
  `usb-Pegasus_Astro_PPBADV_Gen2A_…`. Generic adapters (CH340, FTDI, Prolific) for
  mounts with an EQDIR cable say nothing.
- **Some ports are not for drivers**: the GPS's, which gpsd holds (its `DEVICES`
  report names it), and the ports the profile's other devices use.
- **INDI's telescope and focuser simulators define a serial port** (`/dev/ttyUSB0`)
  that they never open: they connect on any port.

## Decision

- **A serial device without a port is looked for.** When NOCS connects a device
  whose driver defines `DEVICE_PORT` and the profile names no port, or names a
  `/dev/serial/by-id/` port that is no longer plugged in (the device came back on
  another adapter), NOCS tries the serial ports one by one: it sets the port, turns
  the driver's own search off and connects. The first port it connects on is saved
  in the profile, for every role the device plays (a power box's weather too), and
  used from then on. A port in the profile that is plugged in is always used as it
  is: a device that does not answer there may be switched off, and looking for it
  elsewhere would open the other devices' ports.
- **The driver's own search is always off** when NOCS sets a port: with it on, a
  driver that fails on its port goes on to the other devices' ports.
- **The likeliest ports first.** Ports whose stable name contains words of the
  device's name, model or driver (`zwo`, `pegasus`, `ppba`) come first; ports that
  match another device of the profile better than this one come last. The port the
  driver saved, when it is no USB adapter's (a Pi's own UART), is tried last.
- **Ports that are never tried**: those the profile's other devices name, those of
  connected devices, gpsd's (from its `DEVICES` and `DEVICE` reports) and any whose
  stable name says GPS or GNSS.
- **A refused connection is tried once more** on the same port, at once, whether the
  port was found or is the profile's: the second try reads no leftovers.
- **A driver that hangs is restarted** (stopped and started through indiserver's
  FIFO) before the next port. Each try has 20 seconds; a handshake takes one or two.
- **One search at a time**, for the whole rig: two would open each other's ports.
  Its progress is in the state (`equipment.detecting`: the device, the port, the
  attempt of how many), shown on Rig next to the device and in the profile editor.
- **A Detect button** next to the port in the profile editor (mount, focuser, filter
  wheel, power box, weather) runs the same search now (`POST
  /api/equipment/detect-port`) and fills the port in; saving the profile keeps it. A
  connected device just says which port it is on. A driver that does not run is
  started for the question and stopped after; a device it connected is disconnected
  again. The empty choice of the port reads "Found when connecting".
- **Simulators are left alone**: a driver whose executable starts with
  `indi_simulator_` gets no port unless the profile names one.

## Consequences

- An owner never needs to know which port a device is on, and two serial devices
  with the same factory default no longer fight over it: the AM5 and the PPBA of the
  lab connect with an empty profile.
- The profile changes by itself when a port is found: an editor open on it at the
  time keeps its old port until it is reopened, and saving it then forgets the port
  (it is found again at the next connection).
- Trying a port sends another device the driver's handshake (an LX200 query to a
  power box, the PPBA's status request to a mount). The handshakes of the drivers we
  know only ask; a driver whose handshake changes something on whatever answers
  would need to be kept out of the search.
- A search for a device that is unplugged or off tries every free port twice before
  it fails: up to 20 seconds a try (the AM5's driver takes 10), and a driver restart
  for each port it hangs on. On the lab, the AM5 found after trying the PPBA's port
  took 22 s; with the names to go by, the whole rig connects in 1.5 s.
- Restarting a driver that hangs also restarts its other devices; serial drivers
  have one.
- Ports outside `/dev/serial/by-id/` (a Pi's UART, `/dev/ttyS0`) are found only when
  the driver already remembers them; they can still be typed into the profile file.
