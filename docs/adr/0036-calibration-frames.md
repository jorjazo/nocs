# 0036. Calibration frames: flats wizard, darks and bias, and their library

Date: 2026-11-01 · Status: Proposed

## Context

Lights are only half of a night: stacking programs (Siril, PixInsight's WBPP)
calibrate them with darks (same gain, offset, binning, exposure and sensor
temperature), flats (same optical train, filter, rotation and focus, taken while
nothing moved) and bias or dark flats for the flats. Today the user sets each by
hand in Live view: the frame type is there, but nothing picks a flat's exposure,
knows which darks already exist, or says what tonight's lights still lack. Facts
that shape the decision:

- Frames already carry a type (`light`, `dark`, `flat`, `bias`); INDI drivers
  write `IMAGETYP` from `CCD_FRAME_TYPE` and `FOCUSPOS` from a snooped focuser;
  storage puts them in `Flat/<filter>/`, `Dark/` and `Bias/` below the night
  (ADR 0013), and the catalog keeps gain, offset, binning, exposure, sensor
  temperature, filter and size per frame.
- A sequence (ADR 0031) already takes exposure plans of any frame type with their
  own gain, offset and binning, cools and waits for the temperature, survives a
  restart of nocsd, shows in the Session monitor and can be paused. It locks the
  mount too, but locking a role nothing fills costs nothing.
- Plate solves give the camera's rotation on the sky (`solver.last.rotation`); no
  rotator is supported, so rotation changes only by hand, and a meridian flip
  turns it by 180°.
- The reference camera (ASI2600MC) is a colour CMOS: a flat's level must be read
  per Bayer channel, or the strongest one clips first. Its 16-bit FITS hold the
  14/16-bit data scaled to 0–65535; the pedestal (offset) is a few hundred ADU.
- Dark libraries are reused for months on a cooled CMOS; flats are valid only
  while the train stays as it was, in practice for the night unless the camera
  angle is known to match.
- `nocs.sky` gives the Sun's altitude and azimuth at the site, so twilight
  windows for sky flats can be computed offline.
- Making masters (stacking the calibration frames) is what stacking programs do
  well; NOCS's previews do not need calibrated frames.

## Decision

### What is recorded

- **Catalog schema v5:** `frames` gains `focus_position` (`FOCUSPOS` from the
  header), `rotation` (degrees, from the latest plate solve of the same night,
  any frame type; null without one) and `level` (a flat's median in ADU, its
  strongest Bayer channel). An index on `(frame_type, camera)` serves matching.
- NOCS keeps raw calibration frames only; it builds no masters.

### Matching (the library)

A light group is the lights of one camera with the same filter, exposure, gain,
offset, binning, frame size and temperature (within the tolerance). For each,
the newest matching frames of each kind count, from any night:

| Kind | Must match | Within |
|---|---|---|
| Dark | camera, size, binning, gain, offset, exposure (±1 %) | temperature ±2 °C, 180 days |
| Bias | camera, size, binning, gain, offset | temperature ±5 °C, 180 days |
| Flat | camera, size, binning, filter | the same night; or rotation ±1° (modulo 180°) when both are known, 30 days |

- A flat group needs a bias or darks of its exposure; that is reported with it.
- Unknown values (a camera without gain, a sensor without a thermometer) match
  only unknown values. Tolerances are constants in v1; they become settings when
  someone needs it.
- **What is missing** is computed for a night's saved lights or for a saved
  sequence's planned rows (gain, offset and binning from the camera when a row
  leaves them out, temperature from the template's cooling): per group, darks,
  bias and flats wanted (20 darks, 50 bias, 20 flats per filter by default) minus
  those that match.

### Darks and bias: a calibration sequence

- The server turns the missing darks and bias into a sequence (ADR 0031) stored
  as `calibration`: one container per temperature (cool and wait, then bias, then
  darks in turn, longest last), the end warming the camera when asked. No mount,
  guiding or filter steps; bias uses the camera's shortest exposure.
- It runs like any sequence: from the Session tab after the user confirms the
  camera is covered, shown by the monitor, resumed after a restart, pausable.
- Frames above a light-leak threshold are not caught in v1: the confirmation is
  the safeguard.

### Flats: a wizard job

- `FlatsService.run(context, plan)` runs inside any job holding the main camera,
  filter wheel and focuser (and the mount for sky flats), so a sequence can call
  it later; `POST /api/flats` wraps it in a job of kind `flats`. State under
  `flats`: the plan, each filter's exposure, level, frames done and outcome.
- **Level:** the worker reads a frame's median per Bayer channel (or the whole
  mono frame) and reports the strongest, in ADU of the 16-bit scale. The target is
  a fraction of full scale, 50 % by default, accepted within ±10 % (sky: ±20 %).
- **Exposure search** (unsaved test frames): one shortest exposure gives the
  pedestal; then from the filter's last exposure (or 1 s) a frame is scaled
  linearly above the pedestal, ×10 or ÷10 when nearly black or clipped, at most 8
  tries between the plan's shortest and longest exposure (0.01–60 s by default).
  When the longest is still too dim or the shortest too bright the filter fails
  saying what to change (panel, gain, time).
- **Panel flats:** the found exposure for N frames; a saved flat whose level
  leaves the band starts a new search (a warming panel).
- **Sky flats:** within the twilight window from `nocs.sky` (the Sun between −1°
  and −10°), the mount slews to 75° altitude opposite the Sun and stops tracking;
  every frame is measured before it is kept, the next exposure follows from the
  last level and the brightness trend, frames out of the band are dropped, and a
  filter ends when its exposure would leave the limits. At dusk narrowband filters
  go first and broadband last; at dawn the reverse.
- **Matching the lights:** gain, offset and binning default to the night's lights;
  with a focuser, each filter's flats are taken at the focus position of that
  filter's last light of the night. Rotation cannot be set, only recorded.

### API and app

- `GET /api/calibration?night=` or `?sequence=`: light groups with their matches
  and what is missing; flat groups with their bias or darks.
- `POST /api/calibration/sequence`: builds and saves the `calibration` sequence
  from what is missing (counts and warming in the body); started with the
  sequences' own start.
- `POST /api/flats` (job), `GET /api/flats/window` (tonight's dusk and dawn windows).
- `GET /api/nights/{id}/zip?calibration=true` adds the matched calibration frames
  from other nights, under their own night folders.
- The Session tab shows the night's calibration under its frames: each light group
  with darks, flats and bias found or missing, and the actions *Take darks and
  bias* and *Take flats* (a full-screen wizard at `#/flats`).

## Consequences

- One tap after imaging (or before, from the planned sequence) says what is
  missing, and the dark library carries over between nights.
- Darks reuse the sequencer, so they get restarts, pausing and the monitor for
  free; flats need their own loop because each frame depends on the last.
- Rotation is as good as the night's latest solve: a camera turned by hand after
  it makes later flats look matching; the same night always matches.
- Flat panels driven through INDI's light box interface, dark flats taken by the
  wizard itself, a light-leak check and masters are left for later.
- The catalog moves to schema v5 (a backup is kept, ADR 0013).
