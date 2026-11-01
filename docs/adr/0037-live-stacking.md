# 0037. Live stacking (EAA)

Date: 2026-11-01 · Status: Proposed · Plan: [beyond/live-stacking.md](../beyond/live-stacking.md)

## Context

Electronically assisted astronomy (EAA) shows a faint object building up on a
screen as frames arrive: each frame is registered on the first and added to a
running stack. NOCS already has the pieces around it, but not the stacking:

- Every main-camera frame taken by Live view or a sequence goes through
  `CaptureService._finish`, which saves it (loop frames are not saved) and has
  the imaging worker make its preview. Autofocus, solving and polar alignment
  take frames outside that path.
- The imaging worker (ADR 0012) is one spawned process with stateless calls:
  OpenCV debayer (a FITS `RGGB` sensor is OpenCV's `BG`), `sep` stars (2×2
  binned on colour frames), a per-channel MTF stretch and JPEG previews served
  under `/api/previews/`, which observers may read (ADR 0014).
- ASTAP solves a 26 MP frame in ~1.3 s on the Pi (ADR 0018), as a separate
  process; sequences solve only some frames.
- The calibration library (ADR 0036) matches raw darks, bias and flats to light
  groups; NOCS builds no masters.
- The reference rig: ASI2600MC, 6248×4176 (26 MP, 52 MB FITS), a frame every
  ~30 s; on the Pi the worker spends ~1.4 s per preview and nocsd, the worker,
  PHD2 and the drivers use ~800 MB of 8 GB. A 26 MP RGB float32 image is
  ~313 MB; at half resolution (3124×2088) ~78 MB.
- Measured on an x86 PC: a superpixel debayer to half resolution ~150 ms, a
  3-channel `warpAffine` at that size ~20 ms, a per-pixel Welford update with
  kappa-sigma rejection ~0.5 s over whole arrays but ~0.1 s in strips of 32 rows
  (memory bandwidth). The Pi is 2–4× slower than this PC for such work.

## Decision

The options weighed for each point are in [the plan](../beyond/live-stacking.md#decisions).

- **Registration by star triangles.** The 40–60 brightest unsaturated stars from
  `sep`, triangles with each star's nearest neighbours, matched by their side
  ratios; the matched stars go to `cv2.estimateAffinePartial2D` (RANSAC). The
  model is a similarity (rotation, shift, scale ≈ 1): dithers, drift, a meridian
  flip's 180° and field rotation. A frame mirrored relative to the reference, or
  with too few inliers, fails registration. No new dependency (astroalign would
  bring scikit-image and scipy); ASTAP stays out of the per-frame path.
- **Colour by superpixel.** Colour frames are stacked at half resolution, one RGB
  pixel per Bayer cell (the pattern table of ADR 0012); mono frames at full
  resolution up to 16 MP, 2×2 binned above.
- **Online kappa-sigma.** Per pixel and channel the stack keeps a mean, M2 and a
  count (Welford); from the 5th frame a value more than 3σ from the mean is not
  added. Processed in strips. Whole frames are left out when they do not
  register, have fewer than half the stack's median stars, or an HFR above 1.5×
  its median. Memory: ~0.2 GB for a 26 MP colour stack.
- **Calibration from the library when it can.** Masters (median dark or bias,
  flat minus its bias or dark flat, normalised per Bayer channel) are built in the
  worker from the library's matches, at the stack's resolution, cached under
  `<data>/masters/` and never catalogued: they are an internal cache of live
  stacking, not the masters ADR 0036 leaves to stacking programs. Without a dark,
  hot pixels are removed cosmetically.
- **In the imaging worker, stateful.** The stack lives in the worker process,
  under an id nocsd gives it; every call names the stack it expects, so a
  restarted worker cannot add to a stale one. A crash or a restart of nocsd loses
  the stack and the next frame starts another. Stacking runs in the background of
  a capture, never making it wait; at most one frame waits, newer ones replace it.
- **Rendered in the worker.** After each frame (and when the look changes) the
  linear stack is downscaled to 1920 px, stretched per channel (or linked),
  optionally saturated, and written as a JPEG under `/api/previews/`; the state
  `stack` carries counts, the last frame's outcome and the preview's URL.
- **One switch, automatic new stacks.** Stacking is on or off for the main
  camera's light frames from Live view and sequences alike. A new stack starts
  when the target, filter, exposure, gain, binning or frame size changes, after 3
  frames in a row that do not register, or by hand.
- **Saved as a frame of type `stack`.** When a stack with ≥ 2 frames ends, and on
  demand: a float32 FITS (an RGB cube for colour) and a full-size JPEG in
  `<night>/Stack/<target>/`, catalogued (schema v7) so the night's list and zip
  include it; the calibration library ignores it.

## Consequences

- EAA works on the appliance with no other program, and an observer's phone
  shows the stack at an outreach night.
- The worker gains state and ~0.7 GB at peak while stacking, and ~2 s per 26 MP
  frame on the Pi on top of the preview; previews and autofocus measures may wait
  behind a stack update.
- Half-resolution colour stacks are for looking: subs stay on disk, and stacking
  for processing remains Siril's or PixInsight's job.
- The first 4 frames are not sigma-clipped; a satellite in them fades only as
  1/N.
- Losing the stack on a worker crash is accepted in v1; rebuilding from the saved
  subs, LRGB for mono cameras, gradient removal and full-resolution stacking are
  left for later.
