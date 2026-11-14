# Field notes: `v0.1.0rc5` on the rig, 2026-11-12

The night of 2026-11-12 with the GT81 and its 0.8× reducer (profile `william`: 480 mm
× 0.8, 81 mm, f/4.74; ASI2600MC Duo, 3.76 µm; ZWO EAF; AM5). Autofocus was hard all
night (maintainer). Read from the box's catalog (`focus_runs`) and nocsd's journal on
2026-11-14. Times are UTC.

## Autofocus runs

| # | Time | Step | Result | What the points show |
|---|---|---|---|---|
| 1 | 00:14 | 110 | backlash | 6 points (550 steps) at HFR 3.5–3.65, then 7.0, 12.1, 17.3 |
| 2 | 00:18 | 110 | bad fit | Extended 4 points inward; the ends at 11–17 px with ~25 stars |
| 3 | 02:01 | 110 | backlash | Started in focus (HFR 1.47 at 7054); the optics did not move over −1440 and +1440 steps (the first move past 6614, back out to 7054): 5 points at 1.44–1.54, then 3.5, 8.5, 14.7 |
| 4 | 02:03 | 110 | no stars | 5 stars at 7054: going back after run 3 (overshoot shorter than the backlash) left the optics ~430 steps out |
| 5 | 02:23 | 110 | too few stars | From 6354, after focusing by hand: 1 point of 9 with stars |
| 6 | 02:26 | 110 | succeeded | Best 7057, R² 0.98; **last frame HFR 8.02** against `a` 1.52 |
| 7 | 02:28 | 50 | succeeded | Best 7058, R² 0.99; **last frame 8.43** (`a` 1.55) |
| 8 | 02:50 | 30 | succeeded | Best 7059, R² 0.98; **last frame 7.58** (`a` 1.43) |
| 9 | 03:01 | 20 | succeeded | Best 7064, R² 0.97; **last frame 7.42** (`a` 1.52) |

The overshoot was 830 from 02:02 (run 3's suggestion), and whatever was saved before
for runs 1–3.

## Findings

- **Every run that succeeded ended ~190 steps out of focus** (185–194 by each run's
  fitted curve). The check against the first frame (ADR 0021, check 6) passed because
  each run began where the previous one had left the focuser. **Fixed** by
  [ADR 0043](../../adr/0043-autofocus-last-frame-against-the-curve.md): the last frame
  is checked against the curve's best HFR, a miss is approached again with twice the
  overshoot, and a failed run goes back with twice the overshoot.
- **Backlash: 1000 steps or more, and not constant.** The sweeps after the overshoot
  of 830 followed the curve from their first point; the moves to the best focus, with
  the same pattern (past it inward, 830 back out), fell ~190 short; run 3 showed at
  least 1440. No fixed dead band explains all of them. 1000–1450 steps are 2–3 mm of
  drawtube: more than a rack and pinion's play; the EAF's coupling or bracket, or the
  focuser's tension, are worth a look in daylight.
- **Scale.** The V's arms rise 0.042 px per step (`a`/`b` ≈ 1.5/36). A defocused star's
  HFR is 0.354 × the blur disk (Δ/N), so a step is **~2.1 µm**; the critical focus
  zone at f/4.74 (4.88 λ N², 60 µm) is **~28 steps**. A step of 20 suits this train
  (suggested 16–21); 110 put the ends at 11–17 px and lost their stars.

## Next

- **A focuser calibration** ([ADR 0044](../../adr/0044-focuser-calibration.md)): on an
  arm of the V, the backlash each way and its spread, the overshoot that comes back
  to a position (round trips), µm per step and the critical focus zone in steps;
  from the Focus screen, the focuser's sheet in Rig, a *backlash* or *missed*
  failure, and Tonight's focus step while the focuser has no calibration for the
  profile. Checked on the simulators (no backlash) and against a test focuser with a
  dead band.
- Next clear night: calibrate the GT81's focuser (from Tonight); compare the backlash
  each way with 1000–1450, note the spread and whether it warns of slip; then
  autofocus three times and check that each last frame is near the curve's best.
