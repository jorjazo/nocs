# indi_ioptronv3_telescope (iOptron V3)

- **Models:** reviewed for the iOptron GEM45G. The same driver serves the GEM28,
  GEM45, CEM26, CEM40, CEM70, CEM120, the HEM, HAE and HAZ mounts, the iMate and the
  SkyHunter (`drivers.xml`).
- **INDI:** tag `v2.2.5` (the PPA's `indi-bin` 2.2.5 in the dev image), commit
  `1dd9b34f`; no change to these files up to `master` at `2bedd4ae` (2026-11-02).
- **Files:** `drivers/telescope/ioptronv3.cpp`, `ioptronv3driver.cpp`, their headers,
  and the parts of `libs/indibase/inditelescope.cpp` it relies on.
- **Reviewed:** 2026-11-03, from the source only. **Hardware test:** not yet.

[v3]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3.cpp
[drv]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3driver.cpp
[base]: https://github.com/indilib/indi/blob/v2.2.5/libs/indibase/inditelescope.cpp

## Verdicts

| NOCS feature | Verdict | Notes |
|---|---|---|
| Connect, readiness | works | Base properties on connect; the rest defined after it. Serial at 115200 baud (230400 only for a device name with "120"); NOCS does not set the Wi-Fi (TCP) mode. No serial number: settings are kept by device name, `iOptronV3`. |
| Position | caveat | Polled every second (`:GEP#`), but not at all while parked ([1](#1-nothing-is-polled-while-parked)). |
| Altitude and azimuth | works | Not reported; NOCS computes them from the site. |
| Go to | verify | `Ok` when the firmware reports tracking again; the first poll may come before it reports slewing ([4](#4-a-go-to-may-report-ok-before-it-starts)). |
| Go to the zenith (flats) | works | The firmware tracks after every go to, `SLEW` or not; NOCS switches tracking off afterwards. |
| Sync | caveat | A refused sync reports `Ok` ([5](#5-a-refused-sync-reports-ok)); NOCS's sync check warns. |
| Tracking, track modes | works | `TRACK_STATE` follows the mount's status each poll; modes sidereal, lunar, solar, king, custom. |
| Manual motion, slew rates | verify | Nine rates (`1x`…`9x`, labelled 1x to MAX); two show on until the first poll. W/E commands are swapped in the driver for the CEM120 ([6](#6-manual-motion)). |
| Park, unpark | change | Default park position wrong south of the equator ([2](#2-the-default-park-position-is-wrong-south-of-the-equator)); park reported done after the position stops changing for two polls. |
| Home | caveat | `GO` sends `:MH#`, `Ok` when the mount reports home. An abort while homing leaves `TELESCOPE_HOME` `Busy` ([7](#7-home-and-abort)). |
| Abort | works | `:Q#`; an aborted park ends `Alert` (base class). |
| Site and time | caveat | Silently dropped while parked ([1](#1-nothing-is-polled-while-parked)): NOCS sends them again after an unpark. Elevation ignored. The driver reads the mount's own site at connect. |
| Pier side | verify | From `:GEP#` every poll; whether iOptron's east/west is INDI's convention is not documented here ([8](#8-pier-side-and-the-meridian-flip)). |
| Altitude limits | unsupported | The firmware has its own (set from the hand controller); the driver does not expose it. NOCS shows none. |
| Meridian limits | works | `MERIDIAN_ACTION` (`IOP_MB_STOP`/`IOP_MB_FLIP`) and `MERIDIAN_LIMIT.VALUE`; a sequence warns when the mount would stop or flip before NOCS's flip ([3](#3-the-mounts-own-meridian-behaviour)). |
| Meridian flip (sequences) | verify | Depends on the mount's own behaviour at the meridian and on a go to past it changing sides ([8](#8-pier-side-and-the-meridian-flip)). |
| Guiding (PHD2) | verify | Pulses (`:Z…#`) answer at once; `GUIDE_RATE` has `RA_GUIDE_RATE`/`DE_GUIDE_RATE`, which NOCS reads (first element) but PHD2 may not ([9](#9-guiding)). |

## Findings

### 1. Nothing is polled while parked

`ReadScopeStatus` returns at once when the driver believes the mount parked
([v3 L641-643][v3-park-poll]): position, pier side, slew rate and status freeze.
`updateTime` and `updateLocation` do nothing while parked but return success
([v3 L939-950, L952-982][v3-time]), so the base class reports `TIME_UTC` and
`GEOGRAPHIC_COORD` `Ok` with NOCS's values: NOCS believes the mount has them, and its
site check agrees with itself.

NOCS sends the site and the time when the mount becomes ready
([`mount/service.py`](../../server/src/nocs/mount/service.py), `send_time`,
`_send_site`). A mount connected parked (the normal case after a night that ended
with a park) never gets them, and an iOptron without GPS then aims its go tos by its
own clock and site.

**Changed in NOCS (2026-11-03):** the site and the time go again after an unpark
(`MountService.unpark`). An unpark sent by another INDI client still leaves the mount
without them.

Whether the driver believes the mount parked comes from its park data in
`$HOME/.indi/ParkData.xml`, not from the mount: a mount unparked from its hand
controller still shows parked in INDI until NOCS unparks it.

[v3-park-poll]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3.cpp#L641-L643
[v3-time]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3.cpp#L939-L982

### 2. The default park position is wrong south of the equator

Without park data (a fresh install: no `ParkData.xml`), the driver sets the park
position to azimuth 0° (180° south of the equator) and **altitude = latitude**, and
sends it to the mount ([v3 L378-396][v3-park-default]). South of the equator the
latitude is negative, and `setParkAlt` clamps it to 0° ([drv L613-623][drv-park-alt]):
at 30° S the mount parks at azimuth 180°, altitude 0°, the southern horizon below the
pole, instead of the pole at altitude 30°. On an equatorial mount that is the
meridian below the pole, which a German mount reaches counterweights up. "Default"
in `TELESCOPE_PARK_OPTION` has the same mistake with azimuth 0°
([v3 L1215-1224][v3-default-park]).

It runs at the first connection and overwrites the park position stored in the
mount. NOCS parks at the end of every session that fails or ends.

**Before the first park:** set the park position with the mount at the pole
(`TELESCOPE_PARK_OPTION` → current), or check `TELESCOPE_PARK_POSITION` and the
hand controller's park position. **Upstream:** an INDI issue (altitude should be
`|latitude|`, azimuth 180° in the south for the default as well).

[v3-park-default]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3.cpp#L378-L396
[drv-park-alt]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3driver.cpp#L613-L623
[v3-default-park]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3.cpp#L1215-L1224

### 3. The mount's own meridian behaviour

The firmware stops or flips by itself a number of degrees past the meridian:
`MERIDIAN_ACTION` with `IOP_MB_STOP` (the driver's default) or `IOP_MB_FLIP`, and
`MERIDIAN_LIMIT` with one element, `VALUE`, 0–10° ([v3 L180-189][v3-meridian]); the
driver reads both from the mount at connect. `Mount.meridian_limits` first looked
only for `MERIDIAN_FLIP` and `MERIDIAN_LIMIT.LIMIT` (the ZWO names).

NOCS flips 5 minutes (1.25°) past the meridian by default (ADR 0033). With the mount
set to stop at 0° or 1°, it stops tracking before NOCS flips; set to flip, it flips
on its own in the middle of a frame.

**Changed in NOCS (2026-11-03):** `Mount.meridian_limits` reads `MERIDIAN_ACTION`
and `MERIDIAN_LIMIT.VALUE` too, and says whether the mount stops; the mount sheet
shows it, and a sequence pointed east of the meridian warns (an event) when the
mount would stop or flip before its flip point. Set the mount to stop at 3° or more.

[v3-meridian]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3.cpp#L180-L189

### 4. A go to may report Ok before it starts

`Goto` sends `:MS1#` and sets the driver's state to slewing
([v3 L826-857][v3-goto]); each poll then takes the state from the mount's status
(`:GLS#`): tracking makes `EQUATORIAL_EOD_COORD` `Ok`
([v3 L677-722][v3-status], [base L675-720][base-newradec]). If the first poll after
the command still reads "tracking" (the firmware has not switched to slewing yet),
NOCS's go to completes at once, at the old position. Whether that happens is up to
the firmware's timing.

**Test:** watch `EQUATORIAL_EOD_COORD`'s states in the first seconds of a go to.
**Change if seen:** `Mount.goto` waits for `Busy` first, or for the position to
reach the target.

[v3-goto]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3.cpp#L826-L857
[v3-status]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3.cpp#L677-L722
[base-newradec]: https://github.com/indilib/indi/blob/v2.2.5/libs/indibase/inditelescope.cpp#L675-L720

### 5. A refused sync reports Ok

`sync()` reads the mount's one-byte answer to `:CM#` but does not look at it
([drv L649-652][drv-sync]), and `Sync` reports success even when that fails
([v3 L859-880][v3-sync]): the property goes `Ok` with the synced coordinates, and the
next poll shows the mount's own again. NOCS's sync check (`check_sync_kept`) sees the
position go back and warns; a plate-solve-and-sync then retries on a pointing that
did not change.

**Upstream:** an INDI issue (check the `1` in the answer).

[drv-sync]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3driver.cpp#L649-L652
[v3-sync]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3.cpp#L859-L880

### 6. Manual motion

Starts and stops go through the base class: `Busy` while moving, `Idle` stopped, as
`Mount.move` expects. The driver sends `:me#` for west and `:mw#` for east
([drv L389-408][drv-motion]), swapped on purpose because the CEM120 moved the wrong
way; whether the GEM45 agrees is for the test. `initProperties` switches on both 64x
and MAX ([v3 L97-102][v3-rates]) until the first poll reads the mount's own rate (and
never while parked); `Mount.slew_rate` reports the first, `5x`.

[drv-motion]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3driver.cpp#L389-L424
[v3-rates]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3.cpp#L97-L102

### 7. Home and abort

`GO` sends `:MH#` and leaves `TELESCOPE_HOME` `Busy` until a poll reads the status
"home" or "parked" ([v3 L1295-1341][v3-home], [v3 L683-704][v3-status-home]). The
base class's abort does not touch `TELESCOPE_HOME`
([base L1316-1365][base-abort]): after an aborted home NOCS keeps showing the mount
homing until the next home. A park reports done after two polls without motion,
because the firmware keeps saying "slewing" when parked
([v3 L791-807][v3-park-hack]).

[v3-home]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3.cpp#L1295-L1341
[v3-status-home]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3.cpp#L683-L704
[base-abort]: https://github.com/indilib/indi/blob/v2.2.5/libs/indibase/inditelescope.cpp#L1316-L1365
[v3-park-hack]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3.cpp#L791-L807

### 8. Pier side and the meridian flip

The pier side comes with every position (`:GEP#`, [drv L747-786][drv-coords]). NOCS's
flip is a go to the same target once it is past the meridian, then a check that the
side changed (ADR 0033). `:MS1#` asks for the "normal" (counterweight down) position,
so a target just west of the meridian should land on the other side: likely, but
it is firmware behaviour, and the first thing to test. NOCS calibrates guiding again
after every flip, so the convention of the reported side matters only for what the
mount sheet shows.

[drv-coords]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3driver.cpp#L747-L786

### 9. Guiding

The driver adds INDI's guider interface: `TELESCOPE_TIMED_GUIDE_NS`/`WE`, sent as
`:Z{E,C,Q,S}nnnnn#` without waiting for the pulse to end
([drv L555-586][drv-guide], [v3 L1062-1084][v3-guide]), as PHD2 expects.
`GUIDE_RATE` has `RA_GUIDE_RATE` and `DE_GUIDE_RATE` (0.01–0.9 and 0.1–0.99 ×
sidereal, [v3 L155-158][v3-guide-rate]); `Mount.guide_rate` takes the first.

[drv-guide]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3driver.cpp#L555-L586
[v3-guide]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3.cpp#L1062-L1084
[v3-guide-rate]: https://github.com/indilib/indi/blob/v2.2.5/drivers/telescope/ioptronv3.cpp#L155-L158

## Hardware test

Indoors first, telescope balanced or off the mount, a hand near the power switch;
keep the camera clear of the tripod in every step that slews. Record the session
(`dev/tools/indi_record.py --connect iOptronV3 -o dev/recordings/ioptron-gem45g.xml`)
before anything else.

1. **Before NOCS:** write down from the hand controller the firmware versions, the
   park position, the meridian treatment (stop/flip, degrees), the altitude limit,
   whether it has GPS, and its time and site. Back up `$HOME/.indi`.
2. **Connect** with NOCS (port `/dev/serial/by-id/…`). Check `Firmware Info`,
   `GEOGRAPHIC_COORD` (the mount's own site), `TELESCOPE_PARK_POSITION`,
   `MERIDIAN_ACTION`, `MERIDIAN_LIMIT` (finding 2, 3). **Do not park** until the
   park position is right: set it at the pole with "current".
3. **Site and time:** connect once parked and once unparked; after unparking, compare
   the hand controller's time and site with NOCS's (finding 1).
4. **Manual motion:** each direction at a slow and a fast rate; west must decrease
   the RA. Reverse a direction while moving; stop (finding 6).
5. **Go to** a target 30° from the pole: log `EQUATORIAL_EOD_COORD`'s states from
   the command on (finding 4). Abort a go to halfway.
6. **Sync** after a plate solve, away from the pole and near it (finding 5).
7. **Tracking** off and on; each track mode.
8. **Home** (`GO`), and abort a second home halfway (finding 7).
9. **Park and unpark**; time how long park takes to report done.
10. **Meridian:** as in ADR 0033's AM5 spike, a go to 20 min east and 20 min west of
    the meridian, noting the pier side; then a short sequence (30 s frames, flip 2
    min past the meridian) started 4 min east of it (finding 8).
11. **Guiding:** PHD2 calibration and a few minutes of guiding; what guide rate PHD2
    reports (finding 9).
12. **Flats position:** a go to the zenith, only if step 10 showed the counterweight
    stays down.

Rehearsal without the mount: the driver has a simulation mode (`SIMULATION` on
before connecting) that runs the same driver code with a fake mount. It cannot show
firmware behaviour (its pier side never changes, its meridian action is "flip"), but
it checks properties, states and the park position logic.
