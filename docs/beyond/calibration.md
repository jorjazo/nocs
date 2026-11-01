# Calibration frames plan — flats wizard, darks and bias, library

Status: in progress · Last updated: 2026-11-01 · Roadmap: [Beyond v0.1](../roadmap.md#beyond-v01-unordered-backlog) · Decision: [ADR 0036](../adr/0036-calibration-frames.md)

Goal: after (or before) a night of lights, NOCS says which darks, flats and bias
they need, which already exist, and takes the missing ones: darks and bias as a
sequence the user leaves running with the camera covered, flats with a wizard
that finds the exposure by itself, on a panel or the twilight sky.

**Exit (lab, then field):** for a night of ASI2600MC lights in two filters, the
Session tab lists the matching darks from an earlier night, takes the missing
bias and darks unattended, and the wizard takes 20 flats per filter at 50 % ±10 %
of full scale on a panel; the night's zip with calibration holds all of it.

## Stages

| # | Stage | Contents | Check | Status |
|---|---|---|---|---|
| C1 | Library | Catalog v6 (`focus_position`, `rotation`, `level`, index); storage records them; `nocs.calibration.library`: light groups, matching (ADR 0036 table), what is missing for a night or a sequence; `GET /api/calibration`; night zip with matched calibration | Unit tests with a synthetic catalog; API test | Implemented |
| C2 | Darks and bias | `nocs.calibration.darks`: the `calibration` sequence from what is missing (per temperature: cool, bias, darks); `POST /api/calibration/sequence`; the camera's shortest exposure for bias | Unit tests; simulators: a short dark/bias sequence saves to `Dark/`, `Bias/` and the library then reports nothing missing | Implemented: a night of two lights on the simulators got its 3 bias and 2 darks unattended |
| C3 | Flats on a panel | Worker `level` (median per Bayer channel); `CaptureService.keep` (save a frame already taken); `FlatsService.run` with the exposure search and panel frames; `flats` job and state; `POST /api/flats`; focus per filter from the lights | Unit tests of the search with a fake camera; simulators: flats per filter land at the target level | Implemented: every frame is measured before it is kept; on the simulators two filters got their flats at 40 % |
| C4 | Sky flats | Twilight windows from `nocs.sky` (`GET /api/flats/window`); slew opposite the Sun at 75°, tracking off; exposure following the trend; filter order for dusk and dawn; waiting for the window | Unit tests with a synthetic twilight (brightness ×0.9 per 10 s); simulators: the mount goes to the right place | Implemented: unit tests with the Sun at the lab site and a sky halving every 2 minutes; the simulator check waits for a twilight |
| C5 | Session tab and wizard | Calibration card under the night's frames (groups, found and missing, *Take darks and bias* with the "camera covered" confirmation, zip with calibration); `#/flats` wizard (source, filters and counts, target, advanced limits; progress per filter); en/es; `docs/ux.md` | Browser against the simulators, phone and wide, Night mode | Implemented: checked on a phone against the simulators: darks and bias started from the sheet ran in the monitor, the wizard took 3 flats at 50 %, the chips then showed 2/20, 3/20, 2/50 |
| C6 | Lab and field | Lab Pi (lab lock): darks and bias with the cap on, panel flats (or a white screen) on the ASI2600MC; checklist item in the field test for dusk or dawn sky flats | Lab Pi; field test | Lab done in part (below); lit flats and sky flats wait for the field test |

C1 first (everything reads it), then C2 and C3 (independent), C4 on C3, C5 on all,
C6 last. Each stage is pushed to `main` when it passes CI.

## C6 lab check (2026-11-01)

Lab Pi 5, a test nocsd from `main` (2ec1597) on its own port, ASI2600MC Duo at gain 100,
offset 50, bin 1, through the API (the same calls as the Session tab and the wizard).
The EFW was not on USB that day and the scope was capped, so everything ran without
a filter and in the dark.

- **Cooling and lights.** 24.6 → 5 °C in 176 s (cooler at 40 %); 4 lights of 3 s at
  4.3–5.1 °C made one group (no filter, 3 s, 4.7 °C, focuser 7067).
- **Darks and bias.** The library asked for 10 bias and 5 darks of 3 s at 4.7 °C; the
  `calibration` sequence built from them cooled, took 10 bias and 5 darks and finished
  in 71 s, and the group then read complete for darks and bias. Headers: `IMAGETYP`
  `Bias Frame` / `Dark Frame` / `Light Frame`, `GAIN` 100, `OFFSET` 50, `CCD-TEMP`
  3.8–4.0 °C (within the ±2 °C darks match), `FOCUSPOS` 7067, `BAYERPAT` RGGB. The
  driver records a bias as 32 µs (`EXPTIME` 3.2e-05), its shortest exposure, not the
  1 ms asked.
- **Night zip.** 991 MB for the 19 frames with and without `calibration=true`, as it
  should be: that option adds only other nights' frames.
- **Flats, no light.** With the cap on, the wizard measured the pedestal (949 ADU),
  tried 1 s and 10 s (the 10 s limit given) and failed in 26 s with "too dim at 10 s:
  brighten the panel or raise the gain"; at gain 450 and up to 60 s the same after
  74 s (1000 ADU at 60 s). Nothing was kept, nothing reached the library.
- **Per-channel levels: the driver scales raw data by its white balance.** Every
  frame's bias is flat over the sensor but differs per Bayer position: R 519, G 499
  and 500, B 949 ADU. B/G = 1.90 and R/G = 1.04 match ZWO's default white balance
  (WB_B 95, WB_R 52 over 50), so `indi_asi_ccd` applies it to RAW16 too. For
  calibration this is harmless while lights, darks, bias and flats share it (the
  bias subtracts it), and the flats' level (the strongest channel) still guards the
  blue channel against clipping first. But blue clips at ~34 000 ADU of signal, not
  65 000, and the pedestal the wizard measures is blue's, ~450 ADU above green's.
  Follow-up: check `CCD_CONTROLS` WB_R / WB_B on the rig and set them neutral (50)
  for colour cameras, in the profile or on connect.
- Found while preparing it: opened from a night that mixes setups, the wizard took
  the gain, offset and binning of the night's first group, not of the lights that
  miss flats; it now takes the setup of the first missing flats.

Left for the field test (steps 22–23 of [field-test.md](../v0.1/field-test.md)):
flats with real light (a panel, a white screen or the twilight sky) and their
per-channel levels; sky flats at dusk or dawn; darks with the filter wheel present.

## Notes

- Shared files kept small: `api/schemas.py` (calibration and flats state and
  requests), generated types, `api/app.py` wiring, the Session tab.
- The catalog migration number may clash with another session's: whoever lands
  second renumbers (ADR 0013's migrations are an ordered list).
- Later (not in this plan): INDI light boxes (`FLAT_LIGHT_CONTROL`), dark flats in
  the wizard, a flats instruction in sequences (dawn flats at the end of a night),
  a light-leak check on darks, tolerances as settings.
