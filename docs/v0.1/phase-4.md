# Phase 4 plan — Guide & align (guiding)

Status: in progress · Last updated: 2026-10-31 · Roadmap: [Phase 4](../roadmap.md#phase-4--guide--align)

Goal: guided long exposures with dithering, run and watched from a phone, with PHD2
doing the guiding (ADR 0006). Polar alignment, the other half of the phase, needs
the plate solver of phase 3 and gets its own stages once that lands.

**Exit (field test, guiding half):** calibrate and guide from the phone, then take
guided 300 s sub-frames with dithering between them and a total RMS under 1″ with
round stars.

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
| 4.2 | Guide camera handover | PHD2 connects and disconnects its equipment; the guide camera is held for PHD2 meanwhile; Live view shows PHD2's frames | PHD2 looping on the ASI220MM | |
| 4.3 | Calibrate, guide, stop | State machine from PHD2's events; starting to guide as a job (loop, star, guide, settle); calibration reuse; alerts; the mount refuses to move while guiding unless asked to stop it | Guide pulses reach the AM5/AM7 | |
| 4.4 | Guiding statistics | Guide steps kept by the server, RMS in RA, Dec and total (pixels and arcseconds), history for the graph | — | |
| 4.5 | Dithering between frames | Dither in main camera pixels, settling; a series of N frames with a dither every K; guiding RMS per saved frame | — | |
| 4.6 | Guiding UI | Guiding screen (graph, RMS, start/stop, recalibrate, dither settings), Live view chip and frame count, profile editor choice of guiding train; en/es | From the phone | |
| 4.7 | Lab and field test | Lab: connect, loop, pulses; field-test checklist and the test | Exit criterion | |

## Decisions taken for this phase

- PHD2 runs as its own service (a container in development and CI, a systemd unit on
  the Pi); nocsd renders its settings and restarts it to apply them (ADR 0022).
- While PHD2 has the guide camera, NOCS does not expose with it and shows PHD2's
  frames from the BLOBs it receives anyway.
- The mount does not go to, park, home or move by the pad while guiding unless the
  request also stops guiding (a second tap in the app).
- Dithering happens between the frames of a series in Live view; the phase 5
  sequencer reuses the same pieces.

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
