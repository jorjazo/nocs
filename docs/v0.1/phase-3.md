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
| 3.2 | Solve and sync | `solve` job: expose with the main camera, HFR from the worker, hinted then blind, optional sync at mid-exposure; Live view: Solve, result card, Sync | Lab: AM5/AM7 accept a sync | |
| 3.3 | Centre | `center` job: go to → settle → solve → sync or offset → repeat until within tolerance or N attempts; Mount sheet: Go and centre | Simulators with an injected pointing error | |
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
