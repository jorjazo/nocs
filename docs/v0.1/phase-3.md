# Phase 3 plan — Solve & frame

Status: in progress · Last updated: 2026-10-31 · Roadmap: [Phase 3](../roadmap.md#phase-3--solve--frame)

Goal: point the rig at a target from the phone and frame it, without knowing the
sky by heart.

**Exit (field test):** pick NGC 292 (the Small Magellanic Cloud) on the phone; the
mount goes there and centres it within tolerance; then NGC 253. M31 never clears
the hill that hides the north of the lab's site below ~30° (it culminates at ~19°
from −30° latitude).

Stages are small and testable against the simulators (the CCD simulator renders
GSC stars at the mount's position and rotates the frame with `SIM_ROTATION`) and
against real frames from the maintainer's earlier nights. The solver's API is
shared with polar alignment (phase 4) and re-centring and the meridian flip
(phase 5).

## Stages

| # | Stage | Contents | Check | Status |
|---|---|---|---|---|
| 3.1 | ASTAP solver | `nocs.solving`: discovery, star databases and the fields they solve, hints (field from the optical train, position from the mount), downsampling from the measured HFR, a process per solve killed on timeout or cancel, one solve at a time, solutions from ASTAP's WCS (J2000 centre, scale, rotation as shown, mirroring); camera state gains `field`; ASTAP + D05 in dev and CI ([ADR 0018](../adr/0018-plate-solving-with-astap.md)) | Real frames (2600MC, 6200MM, 482MC) and simulator frames solve; rotation matches ASIAIR's | Implemented |
| 3.2 | Solve and sync | `solve` job (`nocs.pointing`): expose with the main camera, HFR from the worker, hinted then blind, offset from the mount, optional sync at mid-exposure; later sync to the last solution if the mount has not moved; failures with a reason; Live view: Solve, Solve and sync, result card, Sync | Lab: AM5/AM7 accept a sync | Implemented |
| 3.3 | Centre | `center` job (`nocs.pointing.center`, callable from any job holding the camera and the mount): go to → settle → solve → sync, or aim off by the error → repeat until within tolerance (1′) or N frames (5); a frame that does not solve is taken again without moving; `centering` state with every frame's error; Mount sheet: Go and centre; centring card in the sheet and Live view | Simulators with an injected pointing error; lab: one run on the AM7 | Implemented |
| 3.4 | Target catalog | OpenNGC (CC BY-SA 4.0) bundled by a pinned build script: Messier, NGC/IC, common names in English and Spanish; search API ([ADR 0019](../adr/0019-bundled-catalogs-and-their-licences.md)) | Tests: parsing, loose ids, NGC 292 / SMC, NGC 253 / Sculptor Galaxy, M 42 in Spanish, aliases, API | Implemented: `dev/catalog/build.py` (OpenNGC v20260501 by SHA-256, `names.tsv`), `nocs.targets`, `GET /api/targets/search`, `/objects/{id}`, `/sources` (observers too) |
| 3.5 | Tonight's sky | Twilights, Moon (altitude, phase), altitude curves, transit, time above a minimum and above a **horizon profile** by azimuth in the site, distance to the Moon | Against an almanac | Implemented: `nocs.sky` (ERFA: `epv00`, `moon98`), `Site.horizon`, `GET /api/sky/tonight`, `/visibility?target=RA,Dec` (observers too; a catalog id once 3.4 lands); within a minute of USNO |
| 3.6 | Plan and Tonight UI | Search, target detail with altitude chart, Go / Go and centre; Tonight: night window and Moon | Phone | Implemented: Tonight (night bar, dark window, Moon, tonight's target, get-ready checklist), Plan → Target (search with tonight's time up, `#/plan/<id>` with the altitude chart over the horizon profile, framing chart, Go / Go and centre to where the frame points), `plan.target` (`PUT`/`DELETE /api/plan/target`, kept in `plan.json`), catalog ids in `/api/sky/visibility`; a sync the mount goes back from is logged as a warning; checked in a phone-sized browser without equipment, not yet on a phone |
| 3.7a | Framing chart (offline) | Tycho-2 subset to V 10 (CC BY-NC 3.0 IGO) by a pinned build script; chart API (stars and objects around a point); canvas chart: gnomonic, north up, stars by magnitude, DSO outlines with position angle, the camera's frame with rotation, crosshair and coordinates, pan / pinch / wheel, Night mode ([ADR 0020](../adr/0020-framing-chart.md)) | Tests: Tycho-2 records, the star file, queries across 0h and the pole, objects reaching into the circle, API; projection (`pnpm test`); NGC 292 and NGC 253 with the simulator camera's field in the browser | Implemented: `dev/catalog/build_stars.py`, `nocs.targets.stars`, `GET /api/targets/chart`, `SkyChart.svelte` at `#/dev/chart` until 3.6 hosts it |
| 3.7b | Framing chart (online and own frames) | The maintainer's own solved frames of the target as background; optional online survey (CDS hips2fits, fetched by the browser, opt-in); "turn the camera N°" helper from a solve (needs 3.2) | Simulators | Implemented (but own frames): opt-in survey image under the chart, fetched by the browser from CDS hips2fits, else NASA SkyView (DSS2 red); the last solved frame drawn dashed where it landed; "Turn the camera N°" from the last solved angle to the framing's, and "Use the camera's angle"; checked in a phone-sized browser (SkyView: NGC 253 under its outline) |
| 3.7c | Own frames as framing background | The maintainer's saved, solved frames of a target under the chart: keep the solution with each saved frame, a downscaled JPEG, and a chart layer | Simulators | |
| 3.8 | Field test | Shares the night with phase 2's ([checklist](field-test.md), step 10) | Exit criterion | |

## Decisions taken for this phase

- Survey imagery is fetched by the browser from CDS when it has internet and the
  user enabled it; the Pi downloads nothing (no internet in the field, and the
  DSS images' terms for redistribution are unclear). The offline chart and the
  user's own frames are the base.
- The offline star chart uses a Tycho-2 subset (ESA/CDS, no copyleft).
- The appliance needs D50: D05 does not solve dense Milky Way fields (ADR 0018).
- Tonight's sky: a night runs from local noon to local noon in local mean solar
  time, like the frame catalog's nights. Rise and set are the upper limb on a flat
  horizon with refraction (Saemundsson, at the pressure of the site's elevation),
  as almanacs give them; no dip of the horizon, since the terrain is the site's
  horizon profile. ERFA's refraction is not used: it is ~15′ short at the horizon.
  Visibility counts the darkest window the night has (astronomical, else nautical,
  else civil) and apparent altitudes against max(minimum, horizon profile).
- "Solve this frame" (first field test: the maintainer expected Solve to solve the
  preview): the capture keeps the main camera's frame behind its preview (a
  preview's file until a newer frame replaces it; a saved frame stays where it was
  saved) with the mount's J2000 position when it arrived; `POST /api/solver/solve`
  with `"frame": "last"` solves a hard link to it in a job that locks nothing.
- Tonight's target lives on the server (`plan.target`), not in the browser: every
  client shows the same one, and the sequence builder (5.13) starts from it. Going
  to a target from Plan also makes it tonight's target; Go and Go and centre go
  where the frame points, which the chart can move off the object.
- Choosing tonight's target also sets the storage target to its catalog label
  (`M 42`), which names the lights' folder and OBJECT header: found in the QA pass
  of 2026-11-01, where lights after Go and centre would have gone to
  `Light/Untitled`. The client makes both calls; Live view can still rename it.
- NOCS's own English names (`names.tsv`) go before OpenNGC's, in their order:
  OpenNGC listed "Sculptor Filament" first for NGC 253.
- A sync is watched for 2.5 s: if the mount reports a position more than 1′ from
  it, NOCS logs a warning (the AM5 near its home position took a sync and went back
  at its next poll, on the lab bench and in the first field test). Not a failure:
  the telescope simulator also reports its old position again after a sync (22.6′
  back) yet aims its next go to by it, so going back does not prove the sync was
  lost. Showing it in the app, and finding whether the AM5 aims by such a sync, is
  left for the field test. Centring skips the watch: its next frame shows whether
  the sync took.

## Measured

- Lab Pi 5, D50, final command line (`-speed slow`, downsampling from HFR and
  frame size), wall time near a hint: M 8 (26 MP) 1.1 s, M 16 in Hα (61 MP) 2.4 s,
  a defocused 61 MP frame at `-z 3` 2.7 s, ω Centauri (2 MP, 0.36°) 0.45 s.
- Laptop: six of the maintainer's frames (ASI2600MC, ASI6200MM, ASI482MC; AM5 and
  AM7) solve within 2′ of the mount's position and, where ASIAIR recorded one, 1°
  of its camera angle; the simulator in 0.04 s, within 0.06′.
- Tonight's sky against USNO (Cerro Tololo, a November and a June night): sunset,
  sunrise, the three twilights and moonrise and moonset within a minute (USNO
  gives minutes); the Moon's quarters within ~1 min (0.013° of elongation);
  Tromsø's midnight sun and polar night. Against astropy: transits of NGC 292 and
  NGC 253 from Diaguitas to the second, the Sun and the Moon within 10″. Lab Pi 5
  (Python 3.13): an almanac 73 ms (once per night and site, then cached; in a
  thread), visibility ~0.9 ms per target (43 ms for 50); laptop 28 ms and 0.4 ms
  (`dev/sky/measure.py`).
- D05 does not solve dense Milky Way fields; the appliance needs D50.
- Lab AM7 (`indi_lx200am5`, INDI 2.2.5): a sync completes in 0.05 s and the mount
  reports the new position at once; 10° from the pole it kept it (a sync 6′ north,
  then back). At home (Dec −90°) it reported the synced position and went back to
  −90° at its next poll. Syncs become points of the mount's multi-star alignment
  (the driver only offers to clear them).
- Simulators: the telescope simulator's index errors (`MOUNT_MODEL`, `MM_ID` and
  `MM_IH` in arcminutes) shift the sky the CCD simulator renders from where the mount
  says it points; a solve measured them within 0.1′. A sync adds a point to the
  simulator's alignment model, which takes effect only once that model has been
  initialised (clear and commit); then the next solve was 0.05–0.2′ from the mount.
  Stale points later moved the sky it renders far from where it says it points.
- Centring on the simulators (index errors 20′ in Dec, 15′ in HA, at J2000 0h −45°):
  syncing, 22.7′ then 0.06′ (two frames); aiming off, 22.6′ then 0.06′. A frame that failed
  to solve kept failing when taken again in place (up to four in a row): the test
  starts the run again with the frame turned.
- Lab AM7 (indoors, so no frame solved): a go and centre slewed 10° from home in
  17 s; the driver reported the slew finished when the position stopped changing
  (no drift during the 2 s settle), and a 1 s frame plus a failed D50 solve took
  ~5 s per attempt. ASTAP CLI-2026.09.01 exits 1 with `ERROR=Not enough stars.` for
  an empty frame (2026.10.30 too), like a failed search: NOCS reads that message
  as `no_stars`.
- With D05, only some of the CCD simulator's 5 s frames of a sparse field solved
  (fewer 10 s frames), and a frame that failed kept failing until the frame changed
  (turned, or moved). On a laptop on 2026-10-31 even 3.1's simulator test failed
  its turned frame, while CI passed it; the integration test retries with changed
  frames and is skipped when none solves.
- Target catalog (OpenNGC v20260501): 13 371 objects (NGC, IC and the addendum),
  110 Messier and 109 Caldwell designations, 171 objects with English names and 115
  with Spanish ones; 347 kB gzipped (1.26 MB of JSON). Lab Pi 5 (Python 3.13):
  loading 0.36 s, +22.5 MB RSS; a search ~0.5 ms, 2 ms at worst (a short id
  prefix, "ngc 2"). Laptop: 0.08 s, the same memory, ~0.12 ms per search
  (`dev/catalog/measure.py`).
- Chart stars (Tycho-2 and supplement 1 to V 10): 357 145 stars, 1.41 MB (xz). A
  chart request (stars and objects around a point, as JSON; `dev/catalog/measure_chart.py`)
  on the lab Pi 5: loading 0.155 s cold, +27 MB RSS; 1–6 ms up to 4° of radius, 4–9 ms
  at 10°, 11–19 ms at 30° (≤ 1500 stars and 300 objects, ≤ 110 kB). Laptop 0.3–4 ms.
- Chart drawing, phone-sized view (375 × 566 chart at 2× pixels, laptop browser): a
  drag redraws every frame at 60 FPS; one draw takes 0.1–0.2 ms at 0.9°, 0.6–0.8 ms at
  9.5°, ~1 ms at 70° (1.5 ms at worst). Not measured on a phone yet.

## QA pass on the simulators (2026-11-01)

Phone width, Night and Dusk, en and es: search, target, Go and centre (centred in 2
frames), Tonight. Fixed on the spot: choosing tonight's target now also names the
lights' folder (see the decisions); Tonight without a chosen profile asked for "the
active profile's" site. Left:

- `plan.target.name` keeps the common name in the language of whoever chose it
  ("M 42 · Gran Nebulosa de Orión" on an English phone). Showing the catalog's name
  in the viewer's language, from `plan.target.id`, would fix it for every screen.
