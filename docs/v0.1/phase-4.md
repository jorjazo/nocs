# Phase 4 plan — Guide & align

Status: in progress · Last updated: 2026-11-01 · Roadmap: [Phase 4](../roadmap.md#phase-4--guide--align)

Goal: polar alignment and guided long exposures with dithering, run and watched from
a phone, with PHD2 doing the guiding (ADR 0006) and NOCS's own three-point polar
alignment on top of the phase 3 solver.

**Exit (field test, guiding half):** calibrate and guide from the phone, then take
guided 300 s sub-frames with dithering between them and a total RMS under 1″ with
round stars ([checklist](field-test-guiding.md)).

**Exit (field test, polar alignment half):** polar align from the phone to within
the tolerance (1′ by default) at the lab's southern site, then the guiding checklist.

Each stage is testable against the INDI simulators and the headless PHD2 of
`dev/compose.yaml`. Guiding needs stars, so the lab can check connecting, looping and
guide pulses, but calibrating and guiding a real mount waits for the sky.

Guiding trains: the guide camera either looks through **its own optics** (a guide
scope) or **through the imaging optics**: an off-axis guider or a guide sensor built
into the main camera, like the ASI2600MC Duo's ASI220MM Mini on the lab rig. The
latter shares the imaging focal length, rotates with the camera (calibrate again
after rotating it) and sits behind the filters.

## Stages

| # | Stage | Contents | Lab check | Status |
|---|---|---|---|---|
| 4.1 | PHD2 service and profile | PHD2 as an external service that nocsd configures: settings file rendered from the profile (devices, pixel size, guiding focal length, calibration step) and applied by restarting PHD2; JSON-RPC client; `guiding` state; guiding through the imaging optics; PHD2 in CI ([ADR 0022](../adr/0022-phd2-as-a-managed-service.md)) | PHD2 service on the Pi with the lab rig's settings | Done on the lab Pi: settings applied in 5 s, PHD2 loops on the ASI220MM through the imaging optics |
| 4.2 | Guide camera handover | PHD2 connects and disconnects its equipment (`/api/guiding/connect`, `disconnect`, `loop`, `stop`, `exposure`); the guide camera is held for PHD2 meanwhile and the camera state says so; Live view shows PHD2's frames; disconnecting the profile releases PHD2 first ([ADR 0023](../adr/0023-guide-camera-and-mount-shared-with-phd2.md)) | PHD2 looping on the ASI220MM | Done on the lab Pi: NOCS's exposures refused while PHD2 loops, a preview of PHD2's frame every ~1.9 s, nocsd answering in 12 ms (p95 27 ms) |
| 4.3 | Calibrate, guide, stop | Starting to guide as a job (`/api/guiding/guide`: loop, a star away from the edges, calibrate if needed or asked, guide, settle), cancelled by `stop`; calibration, settling and PHD2's alerts in the state; a calibration that loses its star is given up; the mount is held while PHD2 calibrates or guides, and go to, park and home take `stop_guiding` | Guide pulses reach the AM5/AM7 | Done: PHD2's 500 ms pulses N/S/E/W reached the lab AM7 (`TELESCOPE_TIMED_GUIDE_*` Busy for 0.5 s); calibrating and guiding wait for the sky |
| 4.4 | Guiding statistics | Guide steps, lost frames and dithers kept by the server per guiding run (`nocs.guiding.stats`); RMS in RA, Dec and total over the last 100 steps not settling, in pixels and arcseconds, with peaks, in `guiding.stats`; `GET /api/guiding/steps?after=` for the graph (observers too); a PHD2 session recorded from the simulators (`dev/tools/phd2_record.py`) | — | Done |
| 4.5 | Dithering between frames | Dither in main camera pixels, converted with both trains' scales, waiting for PHD2 to settle; `dither` and `start` run inside a caller's job (the sequencer's), and `POST /api/guiding/dither` as a job of its own; a series of N frames (`count`) with a dither every K (`dither`); guiding RMS, steps and lost frames per saved frame in the catalog (schema version 3) and the frame list ([ADR 0024](../adr/0024-dithering-between-frames.md)) | — | Done |
| 4.6 | Guiding UI | Guiding screen `#/guiding` (state, graph, RMS, SNR/HFD, calibration; connect, loop, start, recalibrate, dither, stop, disconnect), Live view link with the RMS, guide camera shown as PHD2's, series with dithering; mount sheet and pad wait while guiding with "Stop guiding"; profile editor choice of guiding train; en/es ([ux.md](../ux.md)) | From the phone | Done on the simulators in the browser (calibrate, guide, dither, a 3-frame series with 2 dithers, stop from the mount sheet); the phone waits for the field test |
| 4.7 | Lab and field test | Lab: connect, loop, pulses; field test ([checklist](field-test-guiding.md)) | Exit criterion | Checklist ready; the lab and field tests are pending |
| 4.8 | Polar alignment: spike and math | `nocs.align.polar`, pure functions: the RA axis from three solved frames (the normal of the plane through their directions, in the site's equatorial frame of the date); its error against the celestial pole of the date in altitude and azimuth, north or south; how turning the altitude or azimuth knob moves the axis and the frame, so a later frame tells how far each knob was turned, with the tracking in between; how well a frame reads the knobs. Spike: the telescope simulator's `MOUNT_MODEL` (`MM_ME`, `MM_MA`) as a misaligned mount; a go to at the mount's own Dec as the RA turn ([ADR 0034](../adr/0034-polar-alignment.md)) | Unit tests (both hemispheres, errors from 1′ to 5°, noisy solves, the simulator's model); lab AM7 at home: RA moves keep the pier side and the Dec axis | Implemented; the AM7 check waits for the lab |
| 4.9 | Polar alignment job | `polar_align` job (`nocs.align.service`, `POST /api/align/polar`, `/finish`) holding what a solve holds (refused while guiding, like any slew), never syncing: tracking on, solve; turn the RA axis twice by 30° away from the meridian (a go to at the mount's own Dec; refused within 10° of the pole, if a point would fall under the horizon profile or the minimum altitude, or if the last point reads the knobs poorly); solve each, a frame not solved taken again up to 3 times; fit the axis, and check the turns against those asked for (less the tracking). Then expose and solve again and again at the last point while the user turns the knobs, each frame compared with the previous one updating the error. `polar_alignment` state (the points, the turns, the error in altitude and azimuth and its total, aligned, the latest 60 updates with the knobs' turns); finishing goes back to the start, cancelling stops where it is | Fakes (a tracking mount with a polar error and knobs, failures, refusals); simulators with an injected error and "knobs" turned while it runs | Implemented |
| 4.10 | Polar alignment UI | Full-screen flow `#/polar` like autofocus's: settings (exposure, binning, rotation, east or west), the three points as they are measured, then a target with the error and per-knob instructions in plain words ("Raise the polar axis 12′", "Turn the axis 4′ west") and "Aligned" under the tolerance (1′ by default); reached from Tonight's checklist, the mount sheet and Live view; a suggested start on the meridian halfway between the zenith and the pole; en/es ([ux.md](../ux.md)) | From the phone | Implemented (simulators) |
| 4.11 | Polar alignment lab and field test | Lab: the RA moves on the AM5/AM7; field: polar align, then guide ([checklist](field-test-guiding.md), both halves of the exit) | Exit criterion | Checklist ready; the lab and field tests are pending |

## Decisions taken for this phase

- PHD2 runs as its own service (a container in development and CI, a systemd unit on
  the Pi); nocsd renders its settings and restarts it to apply them (ADR 0022).
- While PHD2 has the guide camera, NOCS does not expose with it and shows PHD2's
  frames from the BLOBs it receives anyway.
- The mount does not go to, park, home or move by the pad while guiding unless the
  request also stops guiding (a second tap in the app).
- Dithering happens between the frames of a series in Live view; the phase 5
  sequencer reuses the same pieces.

For polar alignment ([ADR 0034](../adr/0034-polar-alignment.md)); taken as recommended, the
maintainer having asked the sessions on 2026-11-01 to go ahead and review later:

- The three points come from turning the RA axis 30° and then 30° more **away from
  the meridian**, so the mount never needs a meridian flip in the middle of the
  measurement. Shorter turns cost precision: 10° steps would make a solve's error
  ~80 times larger in the axis, 30° ~9 times. The side comes from the hour angle, not from `TELESCOPE_PIER_SIDE`,
  which the AM5/AM7 do not always report.
- The target is the **true celestial pole of the date, without refraction**. At the
  lab's site (latitude −30°) refraction at the pole's altitude is about 1.7′, more
  than the 1′ tolerance; it is left as an option for later.
- Knob instructions are **relative to the mount's axis** ("raise the polar axis",
  "turn the axis east/west"), so the same words work in both hemispheres.
- The job **never syncs**: the AM5 adds every sync to its own alignment model and
  undoes one near home and the pole (phase 3), and the three points need only the
  solutions. Frames are solved with the measured HFR choosing ASTAP's downsampling
  (at least 2 for a raw colour frame, as on `main`).

## Measured

- PHD2 2.6.14 against the simulators, 1 s exposures: calibration ~42 s, settle
  after starting to guide ~12 s. `set_connected false` leaves the INDI devices
  connected; connecting resets the guide camera's `CCD_FRAME` to the full sensor.
- `phd2 -l` replaces every PHD2 profile, calibration included; with
  `AutoLoadCalibration` and an import only when the settings change, the
  calibration survives restarts ([spike](../spikes/phd2-headless.md)).
- On the lab Pi 5 (stage 4.1), PHD2 2.6.14 from `ppa:pch/phd2` as `phd2@jorjazo`:
  applying the lab rig's settings (restart included) took 5.1 s; PHD2 connected to
  the ASI220MM Mini and the AM7 in 0.4 s and looped 1 s exposures at one frame
  every ~2 s; `set_connected false` left both ZWO devices connected. PHD2 uses
  ~250 MB of memory. Its event server, like indiserver, listens on every
  interface.
- Stage 4.2 on the lab Pi: PHD2 looping 1 s exposures on the ASI220MM Mini through
  NOCS's API. Looping 2.3 s after the request; 17 previews of PHD2's frames in
  30 s (1920×1080, 0.26 s in the worker); `GET /api/state` took 12 ms median,
  27 ms p95 and 58 ms at most while the frames' BLOBs arrived.
- Stage 4.3 on the simulators (1 s exposures): calibrating ~45 s, settling ~10 s;
  the integration test (calibrate, guide, refuse a park, stop for it, guide again
  on the kept calibration) takes ~140 s.
- PHD2 2.6.14 reports `Selected` while it loops with a star selected, not only
  when idle: only `Stopped` means no capture. A star lost while calibrating
  makes PHD2 wait for it forever (lost frames are no calibration steps).
- Stage 4.5 on the simulators: a guided series of 3 × 4 s frames with a 5 px
  dither between them (settling within 1.5 px for 3 s) took ~40 s; every frame
  got its guiding RMS.
- Stage 4.8, the telescope simulator's `MOUNT_MODEL` at Diaguitas (three go tos at
  Dec −30°, hour angles 0, 2 and 4 h): `MM_ME` +60′ fitted as the axis 60.0′ above
  the south pole, `MM_MA` +60′ as 60.0′ east of it (0.3′ off in altitude, second
  order); `MM_MA` is an angle on the sky. The go tos left the Dec axis
  (`MOUNT_AXES`) where it was; the simulator changes pier side at the meridian.
- Stage 4.8, simulated: with three frames 30° apart, 1″ of error in each solve puts
  the axis ~9″ (rms) off; 10° apart ~80″, 45° ~4″; five frames instead of three
  ~10% better. The knobs' amounts and the error they correct differ by 2.5% at 5°
  (second order): the user converges in a few turns.
- Stage 4.9 on the simulators (D05, 5 s frames, 15° turns around 1h −45° J2000, where
  D05 solves): `MM_ME` 40′ and `MM_MA` −25′ fitted within ±3′ from run to run (15°
  turns grow a solve's error ~35 times); the turns measured 15.00 ± 0.02°. Turning the
  altitude "knob" (`MM_ME` −30′) mid-run was read as −30.3′ up and 0.6′ east from one
  frame to the next; frames with nothing turned moved the axis 0.01–0.04′. The
  simulator's `MM_MA` moves the pole east without the turn about the polar axis that
  a turn about the vertical brings, so it does not stand for the azimuth knob.
- Stage 4.10 in the browser (phone width, Night mode, en/es) against the simulators,
  D05, 5 s frames, 30° turns from the suggested start (Dec −60°, half an hour east of
  the meridian, where D05 solves too): `MM_ME` 40′ and `MM_MA` −25′ read as "Lower the
  polar axis 40′" and "Turn the axis 25′ east"; with `MM_ME` alone, turning it to 15′
  read as "25′ down" from one frame to the next, and to 0.3′ as aligned (18″); the
  turns measured 30.0° and 30.0°. A run takes ~45 s to the first knob reading.

## QA pass on the simulators (2026-11-01)

Phone width, en and es: connect, calibrate and guide (total RMS ~0.4″ on the
simulators; calibration took ~3½ min there), a dithered series from Live view
("Dithering" between frames, the guiding link with the RMS), PHD2 still guiding
across a nocsd restart and picked up again. The Session tab now shows each frame's
guiding RMS. Left:

- The calibration's progress line is PHD2's own English text ("calibrating: West
  step 5, dist= 7.7") whatever the app's language: worth turning into "West, step 5
  of …" from the event's fields.
