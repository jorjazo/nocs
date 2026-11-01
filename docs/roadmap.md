# NOCS — Roadmap

Status: draft · Last updated: 2026-10-27

Planning assumptions: one developer, 5–10 hours per week (~250–500 hours per
year). Estimates are rough ranges in hours of focused work. Every phase ends
with something usable on the real rig, so progress is always testable at
night and never only infrastructure.

| Phase | Name | Estimate | Outcome |
|---|---|---|---|
| 0 | Foundations | 40–60 h | Simulated devices visible live in a browser |
| 1 | UX design | 20–30 h | Approved mockups and design system |
| 2 | Connect & capture | 60–80 h | Manual imaging from the phone |
| 3 | Solve & frame | 40–60 h | "Go to M31 and center it" |
| 4 | Guide & align | 50–70 h | Polar alignment and guided long exposures |
| 5 | Focus & sequence | 80–120 h | A full unattended night |
| 6 | Appliance | 50–70 h | Flashable Pi image — **first public release (v0.1)** |
| 7+ | Beyond v0.1 | — | Robustness, remote access, DSLR, EAA, observatory |

Phases 0 and 1 can overlap: backend foundations do not depend on the visual
design, and the UI of phase 2 should not be built before phase 1 ends.

---

## Phase 0 — Foundations

Goal: the skeleton every later phase builds on, verified against simulators.

- Monorepo layout, tooling (uv, ruff, pyright, pytest; pnpm, Vite, Svelte),
  GitHub Actions CI.
- Development container: Ubuntu LTS + INDI (PPA) + simulators + PHD2 + ASTAP.
- Async INDI XML protocol client (connect, getProperties, define/set/new
  vectors, BLOBs) with tests against `indiserver` simulators.
- Typed device abstraction, first version: Camera, Mount, Focuser,
  FilterWheel.
- nocsd skeleton: config, logging, state store with snapshots and patches,
  REST + WebSocket endpoints, job model.
- Minimal web shell: connects, shows live device state (not designed yet).
- Spikes: PHD2 headless under Xvfb; ASTAP solve time on Pi 5; preview
  generation time on Pi 5.

**Exit:** in the dev container, the browser shows simulated devices updating
live, and survives a server restart and reconnect.

## Phase 1 — UX design

Goal: decide what NOCS looks and feels like before building screens.

- Information architecture and navigation (workflow-oriented).
- Mockups of key screens on phone and tablet/desktop: first-run setup and
  pairing, equipment profile, connect, live view/capture, polar alignment,
  focus, framing on sky map, sequence builder, session monitor.
- Design system: color tokens (including red night mode), typography, touch
  components, states (loading, error, offline).
- Click-through prototype validated on a phone in the dark.

**Exit:** approved mockups and design tokens committed to the repo.

## Phase 2 — Connect & capture (manual imaging)

Goal: replace the laptop for manual imaging sessions. Stage plan and status:
[v0.1/phase-2.md](v0.1/phase-2.md).

- Equipment profiles and optical trains; managed `indiserver` driver
  lifecycle.
- Device support (in lab priority order): ZWO cooled camera, ZWO EFW, ZWO
  EAF, ZWO AM5, Pegasus PPBA Gen2, ZWO guide camera, ZWO AM7, iOptron GEM45G.
- Camera: exposure, gain, offset, binning, ROI, cooling with ramps; loop
  preview.
- Imaging pipeline: FITS with full headers, debayer, auto-stretch, preview,
  basic star metrics (count, HFR).
- Storage: destination selection (USB drive), file layout, SQLite catalog,
  download from the web app.
- Mount: manual slew pad, go to coordinates, tracking, park/unpark.
- Focuser and filter wheel manual control; PPBA outputs, dew heaters,
  environment readings.
- Time and location synchronized from the client device.
- Authentication: first-run passphrase and device pairing.
- Web UI for all of the above following the phase 1 design; i18n en/es.

**Exit (field test):** with AM5 + ZWO camera + EFW + EAF + PPBA on the Pi 5,
take a set of manual sub-frames controlled only from a phone.

## Phase 3 — Solve & frame

Stage plan and status: [v0.1/phase-3.md](v0.1/phase-3.md).

- ASTAP integration (hinted and blind solving), FOV from optical train.
- Solve-and-center workflow; sync mount.
- Target search from a bundled catalog (Messier, NGC/IC, common names).
- Framing assistant: sky survey or catalog overlay with the sensor FOV and
  rotation.
- Altitude / visibility charts for tonight.

**Exit (field test):** pick NGC 292 (the Small Magellanic Cloud) on the phone,
the mount goes there and centers it within tolerance; then NGC 253, framed. (M31,
the first choice, never clears the hill north of the lab's site.)

## Phase 4 — Guide & align

Stage plan and status: [v0.1/phase-4.md](v0.1/phase-4.md).

- Polar alignment wizard (three-point method, live correction with clear
  knob-turning guidance).
- PHD2 managed process: profile from guiding train, connect, calibrate,
  guide, stop; guiding graph and RMS in NOCS.
- Dithering between frames.
- Guide camera on guide scope first; OAG as secondary configuration.

**Exit (field test):** polar align from the phone, then guided 300 s
sub-frames with acceptable RMS.

## Phase 5 — Focus & sequence

Stage plan and status: [v0.1/phase-5.md](v0.1/phase-5.md).

- Autofocus: V-curve sweep, HFR fit, backlash, quality checks; temperature
  logging from EAF and PPBA sensors.
- Sequencer engine: containers, instructions, conditions, triggers, recovery
  policies (see design §9.5).
- Triggers: autofocus on temperature/filter/HFR/time, meridian flip, dither,
  re-center.
- End-of-session actions: park, warm camera, power off outputs.
- Sequence templates ("this target, these filters, tonight") and a monitor
  screen with progress, frames, metrics and alerts.
- Session report (frames, HFR, guiding, events).

**Exit (field test):** start a multi-filter sequence at dusk and wake up to a
completed, parked session — including a meridian flip.

## Phase 6 — Appliance

Goal: anyone can flash an image and use NOCS. Stage plan and status:
[v0.1/phase-6.md](v0.1/phase-6.md).

- nocs-system: Wi-Fi access point / station / fallback, USB storage manager,
  health monitoring, reboot/shutdown.
- System clock and site from the client (and geolocation, now over HTTPS) or a
  USB GPS on connect; until then NOCS only corrects its own timestamps
  (ADR 0015).
- indiserver supervision: systemd restarts it when it dies, but nothing yet
  detects an indiserver or driver that hangs without exiting. Design the
  detection and recovery then (see ADR 0011).
- mDNS (`nocs.local`), first-boot experience.
- Raspberry Pi 5 image (Ubuntu Server LTS) with INDI, PHD2, ASTAP database
  and NOCS; boot from USB SSD supported.
- `.deb` packages and apt repository for PC installs; update mechanism.
- User documentation (quick start, supported hardware).

**Exit:** **v0.1 public release.** A fresh Pi 5 flashed with the image runs a
full night from a phone with no other computer involved.

## Beyond v0.1 (unordered backlog)

- Robustness: crash recovery of a running sequence, long-run soak tests.
- SMB share for desktop access to images.
- Remote access outside the LAN: planned in
  [beyond/remote-access.md](beyond/remote-access.md) (ADR 0037, proposed).
- Canon DSLR (gphoto) polish.
- Flats wizard and calibration frame library (darks, bias, flats): planned in
  [beyond/calibration.md](beyond/calibration.md) (ADR 0036).
- Filter wheels: find out which filter sits in each slot (e.g. from the
  brightness of a flat per slot) instead of asking the user (ADR 0016).
- Mosaic planning.
- EAA / live stacking.
- Observatory: roll-off roof, dome, safety monitor, weather automation.
- ASCOM Alpaca / INDIGO adapters.
