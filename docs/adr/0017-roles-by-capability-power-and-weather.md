# 0017. Roles by capability: power and weather, and what each output feeds

Date: 2026-10-31 · Status: Accepted

## Context

Stage 2.10 brings the power box (Pegasus Pocket Powerbox Advance Gen2) under
NOCS control. ADR 0011 gave it one role, `power_box`, resolved without an
interface check because "power boxes declare a mix of interfaces". Facts that
shape this decision:

- INDI 2.x models such a device as a set of **interfaces** on one device. The
  PPBA driver (`indi_pegasus_ppba` 1.4, INDI 2.2.5) declares POWER (`1 << 18`,
  INDI's standard power interface: DC, dew and variable outputs, sensors and
  currents), WEATHER (temperature, humidity, dew point) and AUX; with an
  external motor controller attached it also declares FOCUSER.
- Other devices offer the same capabilities alone or in other mixes: weather
  stations, dew controllers, Pegasus UPB, focusers with a temperature probe.
  The simulator profile already uses the Weather Simulator as its "power box",
  for its readings only.
- Roles may already share a device (a camera with a built-in filter wheel); the
  equipment service connects such a device once.
- The power box does not know what it feeds. On the lab rig one switch drives
  all four 12 V ports, which power the camera and the mount: switching it off
  in the middle of an exposure or a slew loses the frame or the mount's state.
  How a rig is wired belongs to that rig, unlike filter names, which follow the
  wheel (ADR 0016).

## Decision

- **Roles name capabilities, not boxes.** `power_box` is replaced by:
  - `power`: power outputs, dew heaters and auto-dew, input voltage and current,
    resolved by the POWER interface;
  - `weather`: environment readings (temperature, humidity, dew point for now),
    resolved by the WEATHER interface.

  A profile may point both, and `focuser`, at the same device; the simulator
  profile has a `weather` role and no `power`. A profile that still says
  `power_box` loads as `power` plus `weather` on the same device.
- **Facades follow INDI interfaces**: `PowerBox` over the standard power
  interface (with the PPBA's adjustable output, `ADJOUT_VOLTAGE`, as an
  optional extra) and `WeatherSensor` over `WEATHER_PARAMETERS`. Neither knows
  the PPBA by name. The interface's own variable channels (`VARIABLE_CHANNELS`)
  are not used until a box that has them is at hand.
- INDI 2.2.5's power interface matches the elements of a new vector by
  position, not by name: commands always send every element of a vector, in
  the driver's order.
- **Outputs are identified as `<kind>:<n>`** (`dc:1`, `dew:2`, `variable:1`,
  1-based in the order the driver defines them; the PPBA's adjustable output is
  `variable:1`). The profile's `power` role may say what each output feeds and
  give it a label:

  ```json
  "power": {
    "driver": "indi_pegasus_ppba",
    "port": "/dev/serial/by-id/usb-Pegasus_Astro_PPBADV_Gen2A_PPBA6MC1EN-if00-port0",
    "outputs": {
      "dc:1": { "label": "12 V", "feeds": ["main_camera", "mount"] },
      "dew:1": { "label": "Main scope" }
    }
  }
  ```

- **Switching off an output that feeds a busy role is refused** (a job holds
  it, or a slew pad moves the mount) unless the request is forced; the app
  names what the output feeds before it asks for the second tap. An output with
  no `feeds` is guarded by any running job.

## Consequences

- Each screen asks for the capability it needs: Tonight reads `weather`
  whatever device provides it, and a rig with a separate weather station or dew
  controller needs no new code.
- Profiles that point two roles at one device repeat its driver and port; the
  profile editor can offer "same device as".
- The output ids depend on the driver's definition order, which is stable for a
  given driver; a different power box needs its `outputs` written again.
- The wiring makes later steps possible without new decisions: reconnecting the
  roles an output feeds when it is switched back on, showing a fed device as
  "unpowered" rather than failed, and switching outputs off at the end of a
  session (phase 3).
- Recording the ambient temperature and humidity in each frame's FITS headers
  reads the `weather` role.
