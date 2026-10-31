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
| 3.4 | Target catalog | OpenNGC (CC BY-SA 4.0) bundled by a pinned build script: Messier, NGC/IC, common names in English and Spanish; search API (ADR 0019) | — | |
| 3.5 | Tonight's sky | Twilights, Moon (altitude, phase), altitude curves, transit, time above a minimum and above a **horizon profile** by azimuth in the site, distance to the Moon | Against an almanac | |
| 3.6 | Plan and Tonight UI | Search, target detail with altitude chart, Go / Go and centre; Tonight: night window and Moon | Phone | |
| 3.7 | Framing assistant | Canvas chart: offline stars (Tycho-2 to mag ~10) and DSO outlines, sensor field with rotation; the maintainer's own solved frames of the target as background; optional online survey (CDS hips2fits, fetched by the browser); "turn the camera N°" helper (ADR 0020) | Simulators | |
| 3.8 | Field test | Shares the night with phase 2's | Exit criterion | |

## Decisions taken for this phase

- Survey imagery is fetched by the browser from CDS when it has internet and the
  user enabled it; the Pi downloads nothing (no internet in the field, and the
  DSS images' terms for redistribution are unclear). The offline chart and the
  user's own frames are the base.
- The offline star chart uses a Tycho-2 subset (ESA/CDS, no copyleft).
- The appliance needs D50: D05 does not solve dense Milky Way fields (ADR 0018).

## Measured

- Lab Pi 5, D50, final command line (`-speed slow`, downsampling from HFR and
  frame size), wall time near a hint: M 8 (26 MP) 1.1 s, M 16 in Hα (61 MP) 2.4 s,
  a defocused 61 MP frame at `-z 3` 2.7 s, ω Centauri (2 MP, 0.36°) 0.45 s.
- Laptop: six of the maintainer's frames (ASI2600MC, ASI6200MM, ASI482MC; AM5 and
  AM7) solve within 2′ of the mount's position and, where ASIAIR recorded one, 1°
  of its camera angle; the simulator in 0.04 s, within 0.06′.
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
