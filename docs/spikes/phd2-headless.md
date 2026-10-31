# Spike: PHD2 headless

Date: 2026-10-29 · Status: done · Related: [ADR 0006](../adr/0006-reuse-phd2-and-astap.md),
[design §9.4](../design.md#94-guiding)

## Question

Can nocsd drive PHD2 as a managed, headless process — no screen, no manual
setup — through its JSON-RPC API, from equipment connection to guiding and
dithering?

**Answer: yes.** With a virtual display and a generated settings file, PHD2
connected to the INDI simulators, calibrated, guided, dithered and settled
without any interaction. Reproduce with:

```sh
docker compose -f dev/compose.yaml up -d
uv run --project server python dev/spikes/phd2_probe.py guide
```

## Findings

### Packaging

- PHD2 2.6.14 is **not** in the Ubuntu 26.04 archive. The official PPA
  `ppa:pch/phd2` publishes it for 26.04 on **amd64 and arm64**.
- It links against `libindi1`, so the INDI PPA (`ppa:mutlaqja/ppa`) is required
  too. Both PPAs track the current Ubuntu release only (see design §16).

### Running without a screen

- PHD2 is a wxWidgets GUI; it runs fine on **Xvfb** with `DISPLAY` set.
  Resource use while looping/guiding on the simulators: ~90 MB RAM, negligible
  CPU (amd64; Pi 5 numbers pending).
- `xvfb-run` hung as a container's PID 1 (PHD2 never started). A small
  entrypoint that starts Xvfb, waits for its socket and `exec`s PHD2 works
  reliably ([dev/phd2/entrypoint.sh](../../dev/phd2/entrypoint.sh)).
- Modal dialogs do not block the API: problems are reported as `Alert` events
  (e.g. a pixel-size mismatch) that nocsd can surface to the user.

### Profiles and equipment

- On first start PHD2 opens its profile wizard and runs with a temporary
  profile (`.!temp!profile!name!~`) with no equipment. The API cannot create
  profiles or select camera/mount types.
- **Solution:** `phd2 -l <file>` imports a settings file and exits. NOCS
  generates that file and loads it before starting PHD2. Format:

  ```
  PHD Config 1
  /currentProfile	1	1
  /profile/1/name	1	NOCS Simulators
  /profile/1/indi/INDIhost	1	indi
  /profile/1/indi/INDIport	1	7624
  /profile/1/indi/INDIcam	1	Guide Simulator
  /profile/1/indi/INDImount	1	Telescope Simulator
  /profile/1/camera/LastMenuChoice	1	INDI Camera [Guide Simulator]
  /profile/1/scope/LastMenuChoice	1	INDI Mount [Telescope Simulator]
  /profile/1/camera/pixelsize	1	2.4
  /profile/1/frame/focalLength	1	400
  ```

  Every line is `key<TAB>1<TAB>value`: type `1` works for strings, integers and
  floats. **Other type codes are silently dropped**, so a malformed file looks
  like it loaded. PHD2 stores the result in `~/.PHDGuidingV2` (INI format),
  which nocsd could also write directly.
- Camera and mount are selected with the menu labels
  `INDI Camera [<device>]` and `INDI Mount [<device>]`; the INDI device names
  go in `/indi/INDIcam` and `/indi/INDImount`.
- `pixelsize` must match the guide camera, or PHD2 raises an alert about image
  scale changes. Both pixel size and focal length come from NOCS's guiding
  train.

### JSON-RPC

- The event server on port 4400 is on by default. Line-delimited JSON:
  responses carry `jsonrpc`/`id`; everything else is an event (`Version`,
  `AppState`, `GuideStep`, `SettleDone`, …).
- The flow used: `set_connected` → `set_exposure` → `clear_calibration` →
  `loop` → `find_star` → `guide {settle, recalibrate}` → wait `SettleDone` →
  `dither {amount, settle}` → wait `SettleDone` → `stop_capture`.
- Simulator timings (2 s exposures): calibration ~70 s, settle after guide
  start ~11 s, dither settle ~14 s. `get_calibration_data` returns angles and
  rates for the session report.
- `SettleDone.Status` is `0` on success; non-zero must be treated as a failed
  settle (retry / pause the sequence).

## Consequences for NOCS

1. **nocsd owns PHD2's configuration.** For each equipment profile it renders a
   PHD2 settings file from the guiding train (INDI host/port, device names,
   pixel size, focal length) and runs `phd2 -l` before (re)starting PHD2. Users
   never see PHD2's wizard.
2. **One PHD2 process per rig**, supervised by nocsd (start, health via the
   event stream, restart on exit), on its own virtual display.
3. **The guiding module** is a thin async JSON-RPC client plus an event-driven
   state machine (idle → looping → calibrating → guiding → settling), with
   `SettleDone` and `Alert` mapped to job results and user messages.
4. The dev and CI stack now includes PHD2 and the GSC star catalog, so guiding
   can be integration-tested against the simulators.

## Open points

- ~~Pi 5 resource use~~ — measured: 2.9 % CPU average, 126 MiB including Xvfb
  ([pi5-performance](pi5-performance.md)).
- Behavior when indiserver restarts mid-guiding (expect `Alert`/`StarLost`;
  verify recovery).
- Dark library and defect map: no JSON-RPC methods; decide whether NOCS needs
  them or relies on PHD2's multi-star guiding without darks.
- ~~Persisting calibration across sessions~~ — checked in stage 4.1 (see below).

## Follow-up (stage 4.1, 2026-10-31)

Checked against the simulators with PHD2 2.6.14, as input for
[ADR 0022](../adr/0022-phd2-as-a-managed-service.md):

- **`phd2 -l` replaces every profile**: importing a file with profile 2 left no
  profile 1, and re-importing the same profile dropped its calibration.
- **Calibration survives restarts** when the profile sets `AutoLoadCalibration`
  and the file is imported only when it changed: after two restarts,
  `get_calibrated` was true right after `set_connected`.
- **`shutdown`** exits PHD2 cleanly. The container's restart policy brings it
  back in ~3 s, but the second restart failed until the entrypoint removed
  Xvfb's stale `/tmp/.X99-lock`.
- After a forced power-off of the host, PHD2 never came back: its single-instance
  lock `~/phd2.1` held PID 7, which after the restart was the entrypoint script
  itself, so `phd2 -l` waited on an invisible "already running" dialog. The
  entrypoint now removes that lock too; a `docker kill` and start recovers.
- `set_connected false` disconnects PHD2 from indiserver and leaves the camera
  and the mount connected (also the ZWO ASI220MM Mini and AM7 on the lab Pi). Connecting resets the guide camera's `CCD_FRAME` to
  the full sensor and changes neither its binning nor its upload mode.
- While PHD2 loops, another INDI client with BLOBs enabled for the guide camera
  receives every frame (2.6 MB per 1280×1024 simulator frame).
- With 1 s exposures, calibration took ~42 s and the settle after it ~12 s.
- The calibration step that PHD2's assistant computes: 25 px in 12 steps at the
  guide rate, `ceil(25 · scale / (15 · rate) / 12 s / 50 ms) · 50 ms`, at most
  the pulse that still gives 6 steps, divided by cos(declination).
