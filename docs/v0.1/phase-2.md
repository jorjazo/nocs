# Phase 2 plan — Connect & capture

Status: in progress · Last updated: 2026-10-31 · Roadmap: [Phase 2](../roadmap.md#phase-2--connect--capture-manual-imaging)

Goal: replace the laptop for manual imaging sessions, controlled only from a phone.

**Exit (field test):** with AM5 + ZWO camera + EFW + EAF + PPBA on the Pi 5, take
a set of manual sub-frames controlled only from a phone
([checklist](field-test.md)).

The phase is split into small stages, each testable against the INDI simulators
and leaving something usable. Server stages come first; the UI follows the
phase 1 design ([ux.md](../ux.md)). Device work follows the lab priority: ZWO
cooled camera, EFW, EAF, AM5, PPBA, guide camera; AM7 and iOptron GEM45G after
the exit.

## Stages

| # | Stage | Contents | Lab check | Status |
|---|---|---|---|---|
| 2.1 | Equipment profiles and drivers | Profiles as JSON (roles → driver, device, port; optics; site); indiserver driver FIFO; connect/disconnect a profile with per-role status; driver catalog, serial ports; property recorder ([ADR 0011](../adr/0011-equipment-profiles-and-driver-management.md)) | Whole rig connected; recording | Done |
| 2.2 | Jobs, locks and capture | Job model with resource locks; cameras by role (gain/offset, binning, region, frame type, cooling with ramp); exposures as jobs; cameras snoop mount/focuser/wheel for FITS headers | Real frame from the ASI2600MC Duo | Done |
| 2.3 | Image pipeline | `UPLOAD_LOCAL` transfer; worker process: debayer, stretch, JPEG preview, stars and HFR, histogram; loop mode ([ADR 0012](../adr/0012-image-pipeline.md)) | Preview 3.1 s after a 1 s exposure | Done |
| 2.4 | Storage and catalog | Destinations (mounted drives, microSD warning), file layout, NOCS FITS headers, SQLite catalog, frame list and downloads ([ADR 0013](../adr/0013-storage-and-catalog.md)) | Frames on a USB drive | Done |
| 2.5 | Authentication and pairing | First-run passphrase, device pairing with revocable tokens, read-only observer, Origin checks; plain HTTP limits ([ADR 0014](../adr/0014-authentication-and-pairing.md)) | — | Done |
| 2.6 | Web app foundation | Design tokens and themes, navigation, router, i18n (en/es), typed API client, first run and pairing screens, Rig status and connect | Pair and connect from a phone | Done |
| 2.7 | Live view | Preview with zoom, metrics, histogram, exposure settings, loop / capture / save, cooling; night mode tints previews | ZWO camera from the phone | Done |
| 2.8 | Focuser, filter wheel, profile editor | EAF (absolute/relative moves as jobs, abort, temperature), EFW (filter changes as jobs; filter names kept per physical wheel, [ADR 0016](../adr/0016-settings-per-physical-device.md)), main camera exposures lock both; profile editor (devices, roles, optics, ports, site) | EFW and EAF | Done |
| 2.9 | Mount | Slew pad with a server-side dead man's switch, go to coordinates (J2000 → JNow) and alt/az, tracking, park/unpark, home; time and site from the client to the mount; frame times corrected when the Pi's clock is off ([ADR 0015](../adr/0015-mount-control-and-client-time.md)) | AM5 | Server done and checked on the lab AM7 (same driver); AM5 and UI pending |
| 2.10 | Power box | `power` and `weather` roles by capability; PPBA power outputs, adjustable output, dew heaters and auto-dew, environment readings; profiles say what each output feeds, and cutting one that feeds a busy device is refused (tested against recorded properties and `dev/tools/fake_ppba.py`: no simulator exists) ([ADR 0017](../adr/0017-roles-by-capability-power-and-weather.md)) | PPBA | Done: dew A PWM, auto-dew and the adjustable output on the lab PPBA through the API (voltmeter: 0 V off, 8 V back on); UI checked against the fake box |
| 2.11 | Guide camera and field test | Guide camera role with previews (guiding is phase 4); FITS header review on real frames; field test ([checklist](field-test.md)) | Exit criterion | Guide camera and header review done and checked on the lab rig; field test pending |

After the exit: AM7 and iOptron GEM45G (profiles and driver quirks).

Pending, without a stage yet:

- **Save a preview after the fact.** Live view (2.7) decides before the exposure
  whether a frame is saved (a Save toggle next to the shutter); loop and preview
  frames are discarded once analysed. The server should keep the FITS behind the
  latest preview of each camera, with the facts read when it was taken (gain,
  temperature, filter, target), so the phone can save it later.
- **Saved sites.** A site lives in each profile; a list of saved sites shared by
  profiles (and offered to the mount) would avoid typing it again per rig.
  Nothing checks a site against reality before geolocation or GPS (phase 6).

## Decisions taken for this phase

- No privileged operations yet (they belong to nocs-system, phase 6): USB drives
  are mounted by the OS (fstab on the lab Pi), the system clock is not set;
  time and site go to the mount from the client, and when the Pi's clock is off
  NOCS timestamps frames with the client's time instead (ADR 0015).
- indiserver runs as its own service with a driver FIFO (ADR 0011); on the lab
  Pi, `dev/pi/indiserver@.service`.
- Mockups live on a private design canvas; [ux.md](../ux.md) is the reference for
  the UI stages.
- Before guiding (phase 4) the guide camera must not use `UPLOAD_LOCAL`, which
  would stop PHD2's BLOBs (ADR 0012).
- Until HTTPS (phase 6) the web app has no geolocation, service worker or wake
  lock: the site is entered by hand, time comes from the client (ADR 0014).
- To review in phase 6: an indiserver or driver that hangs without exiting is
  not detected yet.

## Measured on the lab Pi 5

See [spikes/pi5-performance.md](../spikes/pi5-performance.md): a 26 MP color
frame is saved by the driver 0.7 s after the exposure; its preview takes 1.4 s in
the worker; the event loop stays free.
