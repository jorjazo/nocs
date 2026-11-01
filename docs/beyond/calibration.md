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
| C3 | Flats on a panel | Worker `level` (median per Bayer channel); `CaptureService.keep` (save a frame already taken); `FlatsService.run` with the exposure search and panel frames; `flats` job and state; `POST /api/flats`; focus per filter from the lights | Unit tests of the search with a fake camera; simulators: flats per filter land at the target level | Planned |
| C4 | Sky flats | Twilight windows from `nocs.sky` (`GET /api/flats/window`); slew opposite the Sun at 75°, tracking off; exposure following the trend; filter order for dusk and dawn; waiting for the window | Unit tests with a synthetic twilight (brightness ×0.9 per 10 s); simulators: the mount goes to the right place | Planned |
| C5 | Session tab and wizard | Calibration card under the night's frames (groups, found and missing, *Take darks and bias* with the "camera covered" confirmation, zip with calibration); `#/flats` wizard (source, filters and counts, target, advanced limits; progress per filter); en/es; `docs/ux.md` | Browser against the simulators, phone and wide, Night mode | Planned |
| C6 | Lab and field | Lab Pi (lab lock): darks and bias with the cap on, panel flats (or a white screen) on the ASI2600MC; checklist item in the field test for dusk or dawn sky flats | Lab Pi; field test | Planned |

C1 first (everything reads it), then C2 and C3 (independent), C4 on C3, C5 on all,
C6 last. Each stage is pushed to `main` when it passes CI.

## Notes

- Shared files kept small: `api/schemas.py` (calibration and flats state and
  requests), generated types, `api/app.py` wiring, the Session tab.
- The catalog migration number may clash with another session's: whoever lands
  second renumbers (ADR 0013's migrations are an ordered list).
- Later (not in this plan): INDI light boxes (`FLAT_LIGHT_CONTROL`), dark flats in
  the wizard, a flats instruction in sequences (dawn flats at the end of a night),
  a light-leak check on darks, tolerances as settings.
