# Driver reviews

INDI standardises property names, not behaviour: every driver is its own code, and
each ZWO device needed something of its own (the gotchas in `CLAUDE.md`). Before NOCS
lists a device as supported, someone reads its driver's source against what NOCS
relies on, writes down what will work, what needs a change in NOCS and what is not
supported, and turns the open questions into a short test for the real hardware.

A review is not a test: it finds what can be known from the code and tells the
hardware test where to look. Sources: [indilib/indi](https://github.com/indilib/indi)
(core and standard drivers, `drivers/`) and
[indilib/indi-3rdparty](https://github.com/indilib/indi-3rdparty) (vendor drivers:
ZWO, QHY, ToupTek, gphoto…). Review the tag of the release the PPA ships
(`apt-cache policy indi-bin`, or the dev image's `dpkg -l indi-bin`), and check with
`git log <tag>..master -- <files>` whether the driver has changed since.

## Notes per driver

One file per driver executable, `docs/drivers/<executable>.md` (one driver serves
many models: `indi_ioptronv3_telescope` drives 19 iOptron mounts). It starts
with:

- the models it was reviewed for, the INDI tag and commit, the files read and the
  date;
- a table with one row per NOCS feature (from the checklist below) and a verdict:

  | Verdict | Meaning |
  |---|---|
  | works | the code does what NOCS expects |
  | caveat | works, with a limit worth knowing (shown to users in `docs/user/hardware.md`) |
  | change | NOCS needs a change to support it; the change is listed |
  | unsupported | the driver cannot do it; NOCS must cope (and does, or the change says how) |
  | verify | the code cannot tell (firmware, timing): the hardware test checks it |

- findings, each with links to the source lines at the reviewed tag;
- the hardware test: numbered steps, safest first, each saying what to look for;
- after the test, its results (date, firmware, what changed), and the verdicts
  updated.

Findings that are driver bugs go upstream as INDI issues (after the maintainer
agrees), linked from the notes. The users' list of tested hardware,
[`docs/user/hardware.md`](../user/hardware.md), links each reviewed driver to its
notes and repeats the caveats as known quirks.

## Checklist

What NOCS relies on, by facade (`server/src/nocs/devices/`). Every review answers the
common part and the part for its device type.

### Every device

- **Readiness.** Which properties the driver defines before and after `CONNECT`, and
  which first appear with placeholder values (`CCD_INFO` at 0×0). The facade's
  `REQUIRED` and `not_ready()` must wait for the real values.
- **Commands complete on `Ok`, fail on `Alert`** (`Device.command`). For each command
  NOCS sends: does the driver report `Ok` only when the action is done, or at once
  (then the facade needs a `done` condition)? Does a refusal end in `Alert`, or in
  `Idle`, or in nothing (then NOCS waits for the timeout)? Does the driver log the
  reason as a message just before the `Alert` (NOCS shows it)?
- **State conventions** that differ from `Ok` = done: `Busy` = on, `Idle` = off.
- **Silence.** Does the driver do long work on its main thread (it then answers
  nothing, and the probe of ADR 0030 may take it for hung)?
- **Serial number** (`SERIAL_NUMBER`, `Serial Number`): without one, settings per
  physical device (ADR 0016) fall back to the INDI device name.
- **Device name and connection**: the default device name, `DEVICE_PORT` and baud
  rate defaults, other connection modes (TCP, Wi-Fi) NOCS does not set.
- **Persistent state** the driver keeps in `$HOME/.indi` (configuration, park data,
  filter names) and what happens on a fresh install.

### Mount (`Mount`, `mount/service.py`, ADR 0015, 0033)

- `EQUATORIAL_EOD_COORD` (JNow) and `ON_COORD_SET`: a go to ends `Ok` when it
  arrives and tracks; with `SLEW`, does the mount stop (then `Idle`, never `Ok`)?
  Can the first poll after a go to report the old position as `Ok`?
- Sync: refused syncs reported as `Alert`, or `Ok` regardless? Syncs near the pole
  or home position kept?
- `TELESCOPE_TRACK_STATE`, `TELESCOPE_TRACK_MODE` (element names `TRACK_*`).
- Manual motion: `TELESCOPE_MOTION_NS`/`WE` (`Busy` while moving, `Idle` when
  stopped), directions not reversed, `TELESCOPE_SLEW_RATE` names and labels, which
  rate is on at start.
- `TELESCOPE_PARK` (done when?), park position defaults (hemisphere!), `UNPARK`;
  `TELESCOPE_HOME` with `GO`; `TELESCOPE_ABORT_MOTION` during a slew, park and home.
- `TIME_UTC`, `GEOGRAPHIC_COORD`: does the mount get them always, or not while
  parked? Does the driver read the mount's own site at connect?
- `TELESCOPE_PIER_SIDE`: reported, after go to and while tracking; INDI's convention
  (the side the telescope is on) or the mount's own?
- Limits NOCS shows: `ALTITUDE_LIMIT_*`, `MERIDIAN_FLIP` + `MERIDIAN_LIMIT`, or the
  driver's own names. The mount's own behaviour at the meridian (stop, flip, keep
  tracking) against NOCS's flip a few minutes past it.
- Guiding through PHD2: `TELESCOPE_TIMED_GUIDE_NS`/`WE`, `GUIDE_RATE` element names.

### Camera (`Camera`, `imaging/capture.py`, ADR 0012)

- `CCD_INFO` placeholders, `CCD_EXPOSURE` limits and countdown, `CCD_ABORT_EXPOSURE`.
- Frame delivery: `UPLOAD_MODE` with `UPLOAD_LOCAL`, `UPLOAD_SETTINGS`, the next
  update of `CCD_FILE_PATH`; file names reused; BLOB format (FITS, or a raw format
  such as a DSLR's).
- `CCD_FRAME_TYPE`, `CCD_BINNING`, `CCD_FRAME`, `CCD_CFA` (Bayer pattern and offsets).
- Gain and offset: `CCD_GAIN`/`CCD_OFFSET` or `CCD_CONTROLS` elements.
- Cooling: `CCD_TEMPERATURE` (writable only when cooled), `CCD_COOLER`,
  `CCD_COOLER_POWER` units, `CCD_TEMP_RAMP`.
- Snooping for FITS headers: `ACTIVE_DEVICES`, `SCOPE_INFO`.
- Several cameras on one driver (all ZWO cameras: devices defined one after another).

### Focuser (`Focuser`, `focus/`, ADR 0021)

- `ABS_FOCUS_POSITION` (required: relative-only focusers are not supported),
  its element's min/max against `FOCUS_MAX`.
- Move done on `Ok` at the target, or earlier; `FOCUS_ABORT_MOTION` and what the
  motor does after an abort (the EAF goes on to its target).
- `FOCUS_TEMPERATURE`; backlash handled by the driver or not.

### Filter wheel (`FilterWheel`, `filters/`)

- `FILTER_SLOT` `Busy` while turning, or not at all (the EFW); done on `Ok`.
- `FILTER_NAME`: where names are kept (`$HOME/.indi`, or the device), `Alert` when
  they cannot be saved.

### Power box (`PowerBox`, INDI ≥ 2.1 power interface)

- The standard `POWER_*`, `DEW_*`, `USB_*`, `ADJOUT_VOLTAGE`, `AUTO_DEW_*`
  properties, or driver-specific ones; duty cycle units; placeholder vectors.

### Weather (`Weather`)

- `WEATHER_PARAMETERS` element names (`WEATHER_TEMPERATURE`, `WEATHER_HUMIDITY`,
  `WEATHER_DEWPOINT`).

## Order

1. **iOptron GEM45G** (`indi_ioptronv3_telescope`): the pilot, before the maintainer
   tests the mount. [Notes](indi_ioptronv3_telescope.md).
2. Other mounts, the most varied devices and the riskiest: EQMod/Sky-Watcher
   (`indi_eqmod_telescope`), Celestron (`indi_celestron_aux`, `indi_celestron_gps`).
3. Other camera makers: QHY (`indi_qhy_ccd`), ToupTek and its OEMs (one source,
   `indi-toupbase`, built as `indi_toupcam_ccd`, `indi_altair_ccd`…).
4. Canon DSLRs through gphoto (`indi_canon_ccd`, `indi_gphoto_ccd`): no cooling,
   bulb exposures, raw frames.
5. A relative-only focuser, to decide whether NOCS supports them.
