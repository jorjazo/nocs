# Live stacking plan — EAA

Status: decided, implementation starting · Last updated: 2026-11-01 · Roadmap: [Beyond v0.1](../roadmap.md#beyond-v01-unordered-backlog) · Decision: [ADR 0037](../adr/0037-live-stacking.md)

Goal: as the main camera's light frames come in, NOCS registers each one on the
first, adds it to a running stack and shows the growing stack on the phone, so a
faint galaxy builds up in front of the user (and of anyone watching as an
observer) within a few frames. Live stacking is for looking, not for processing:
the subs stay on disk for Siril or PixInsight; the stack can be saved as a FITS
and a JPEG.

**Exit (lab, then field):** on the lab Pi with the ASI2600MC, 30 s frames of one
target, dithered every 3 frames and with a meridian flip in the middle, stack
into one image shown on a phone ≤ 5 s after each frame is saved; the worker's
extra cost stays ≤ 3 s per frame and ≤ 1 GB of memory; a satellite trail in one
sub is gone from the stack; with darks and flats in the library they are applied.

## What we have to build on

- **Frames.** Every frame of the main camera goes through
  `CaptureService._finish` (Live view's series and loop, sequences, flats), which
  saves it (unless loop) and asks the imaging worker for its preview. Autofocus,
  solving and polar alignment take theirs with `take`, outside `_finish`, so they
  would never reach a stack.
- **The imaging worker** (ADR 0012): one spawned process, stateless calls with a
  file path, results small; OpenCV for debayer and resize, `sep` for stars (2×2
  binned on colour frames), per-channel MTF stretch, JPEG 85, previews under
  `/api/previews/` (readable by observers, ADR 0014).
- **Plate solving** (ADR 0018): ASTAP hinted in ~1.3 s on the Pi, a separate
  process; sequences solve only some frames (pointing checks every N).
- **Calibration library** (ADR 0036): raw darks, bias and flats in the catalog,
  matched to light groups by `nocs.calibration.library`; NOCS builds no masters.
- **Pi 5 budget** ([spike](../spikes/pi5-performance.md),
  [soak](../spikes/pi5-soak.md)): a 26 MP frame (6248×4176, 52 MB) every ~30 s;
  the worker spends ~1.4 s on its preview; nocsd, worker, PHD2 and drivers take
  ~800 MB of 8 GB; the event loop must not touch pixels or files.

## Stages

| # | Stage | Contents | Check | Status |
|---|---|---|---|---|
| S1 | Registration | `nocs.stacking.register`: brightest stars from `sep` (positions, flux), triangle invariants from each star's nearest neighbours, matched by nearest invariant, votes → `cv2.estimateAffinePartial2D` (RANSAC, similarity); acceptance rules (inliers, scale ≈ 1, no reflection) | Unit tests on synthetic star fields: shifts, rotations (0–180°), 10 % false stars, 30 % missing stars, a mirrored field refused, too few stars refused; transform within 0.05 px and 0.01° | Implemented: 18 tests; ~5 ms per frame with 50 stars |
| S2 | Stack core | `nocs.stacking.stack` (in the worker): load, superpixel debayer (RGGB is OpenCV's "BG", so the same pattern table) or mono, stars on the stack's own resolution, register on the reference, `warpAffine`, online kappa-sigma (Welford) by strips, frame quality gate, render (stretch, JPEG), save (FITS float32); `ImageWorker.stack_*` calls; worker-side state | Unit tests with synthetic Bayer frames of known shift and rotation: noise falls as 1/√N, a satellite trail in one frame is rejected, channel order right on an RGGB frame, the gate drops a cloudy frame; `dev/bench/stack_bench.py` per-frame cost | Implemented: 21 tests plus one through the real worker; bench below |
| S3 | Calibration | Masters for the stack from the library's matches: median dark (or bias), flat minus its bias or dark flat, normalised per Bayer channel; built in the worker in strips, cached under `<data>/masters/`; cosmetic hot-pixel removal when there is no dark | Unit tests with a synthetic catalog and frames (a hot pixel and a vignetted flat corrected); cache reused; bench of building a master from 20 frames | Planned |
| S4 | Service and API | `LiveStackService`: on/off, hook on main-camera lights from `_finish` (background, newest frame wins), new stack on a change of target, filter, exposure, gain, binning or size, or after 3 frames that do not register; state `stack`; `POST /api/stack` (on/off), `/api/stack/reset`, `/api/stack/save`, `PUT /api/stack/look`; schemas + TS types; worker death handled | Unit tests with a fake worker; API tests; simulators: a series with mount nudges between frames (GSC stars) stacks every frame and reports the shifts | Planned |
| S5 | Web UI | Live view: *Stack* toggle, the stack in the viewer (switch to the last sub), frames / rejected / total time, *New stack*, *Save*, look sheet (background, strength, saturation); Session monitor shows the stack while a sequence stacks; en/es; `docs/ux.md` | `pnpm check`, `pnpm test`; browser against the simulators, phone and wide, Night mode; an observer sees it | Planned |
| S6 | Saving | Stack as FITS (float32, RGB cube) + JPEG in `<night>/Stack/<target>/`, catalogued as `stack` (catalog v7; ignored by the calibration library), at the end of a stack and on demand; listed under the night and in its zip; WCS from a solve of the reference when ASTAP is available | Unit tests (catalog migration, layout); API test; the saved FITS opens in Siril/astropy with the right orientation and WCS | Planned |
| S7 | Lab and field | Bench on the lab Pi; a soak night with stacking on (memory, worker time, event loop); field test checklist item (EAA on a galaxy, dithers and a flip) | Lab Pi; field test | Planned |

S1 and S3's master building are independent; S2 needs S1; S4 needs S2; S5 needs
S4; S6 needs S4 (and S5 for its button); S3 slots in before S4 or after S5
without changing the API. Each stage is a PR to `main` that passes CI.

## Decisions

Each was open with a recommendation; on 2026-11-01 the maintainer accepted every
recommendation below (D1–D10), and ADR 0037 records them.

### D1. Registration: how to find each frame's transform

| Option | For | Against |
|---|---|---|
| **Own triangle matching on `sep`'s stars + OpenCV's RANSAC** | No new dependency (numpy, OpenCV, sep are there); the stars are already detected for the preview's metrics; ~10–50 ms per frame; sub-pixel from the fit over tens of stars | ~250 lines of our own to get right and test |
| astroalign | Proven, the same algorithm | Pulls scikit-image and scipy (~100 MB, more arm64 wheels to trust), slower, its own `sep` call |
| ASTAP's solution per frame | Already integrated; absolute WCS | ~1.3 s of CPU and a process per frame on the Pi, needs every frame to solve (clouds, few stars), and accuracy of a fraction of a pixel is not guaranteed; still needs warping |

**Recommendation: own triangle matching.** The 40–60 brightest stars that are
not saturated or at the edge; for each star, triangles with its 4–5 nearest
neighbours (sides sorted, invariants = two side ratios); invariants matched by
nearest neighbour (brute force is fine at ~500 triangles); each matched triangle
votes for 3 star pairs; the pairs with most votes go to
`cv2.estimateAffinePartial2D` (RANSAC, 4 degrees of freedom: rotation, scale,
shift). Accepted when ≥ 6 inliers (and ≥ 30 % of the candidate pairs), scale
within 1 ± 0.5 %, residual RMS < 1 px. ASTAP stays out of the per-frame path; it
may solve the reference once for the saved FITS's WCS (S6).

### D2. Transform model, rotation and mirror

- **Similarity** (rotation + shift, scale fixed near 1): covers dithers, drift,
  the 180° of a meridian flip and an alt-az mount's field rotation. No
  homography or distortion model: across a frame of 1–5° the residuals stay
  under a pixel at EAA scales.
- **Mirror:** a frame mirrored relative to the reference cannot happen on one
  optical train; the triangle invariants match it but the similarity fit does
  not, so it fails registration with a clear reason ("mirrored: did the train
  change?"). Not handled further.
- Frames are warped to the reference's geometry (the first accepted frame);
  pixels a dither or flip leaves uncovered are NaN and simply count fewer frames.
  The stack's edges are cropped to where at least half the frames cover, at render.

### D3. Colour and resolution of the stack

| Option | Memory of the accumulators (26 MP OSC) | Cost |
|---|---|---|
| Full-resolution debayer (bilinear/VNG), RGB | ~0.8 GB (mean, M2, count) + ~0.6 GB transient | warp and accumulate 4× larger |
| **Superpixel (2×2 → one RGB pixel), 3124×2088** | ~0.2 GB | ~0.15 s debayer on x86 (~0.3 s Pi) |
| Stack raw CFA, debayer at render | ~0.2 GB | registration must move whole Bayer cells only (2 px steps) or break colour |

**Recommendation: superpixel for colour frames**, via the existing pattern
table (FITS `RGGB` → OpenCV `BG`; superpixel picks R, (G1+G2)/2, B from each
cell by the same pattern). No interpolation artefacts, exact for dark
subtraction, and 3124 px is still above the 1920 px preview. **Mono:** full
resolution up to 16 MP, 2×2 binned above (a 26 MP mono sensor also stacks at
6.5 MP). Full resolution can come later as an option on a PC.

### D4. Combining: mean, sigma clipping, memory

| Option | Memory | Removes satellites and planes |
|---|---|---|
| Running mean (sum + count) | 1 accumulator | No |
| Kappa-sigma over a window of the last N frames | N frames (N = 10: ~0.8 GB at half resolution) | Within the window; a full re-stack per frame |
| **Online kappa-sigma (Welford): per pixel mean, M2, count; a new value further than k·σ from the mean is not added** | 3 accumulators (~0.2 GB) | Yes, from the ~5th frame on |

**Recommendation: online kappa-sigma**, k = 3, rejection from the 5th frame
(before, a plain mean), per channel, processed in strips of ~32 rows so it stays
in cache: ~0.1 s per 6.5 MP RGB frame on this x86 against ~0.5 s for whole-array
numpy (measured, see the budget below). Plus a **frame gate**: a frame is left
out (and counted as rejected, with its reason) when it does not register, has
fewer than half the stack's median star count, or an HFR above 1.5× the stack's
median (clouds, wind, a lost guide star).

A satellite in one of the first 4 frames survives (no σ yet); acceptable for
EAA, and it fades as 1/N. Exposures stay equal within a stack (D8), so no
weighting by exposure; weighting by noise is left for later.

### D5. Calibration

ADR 0036 builds no masters, but a live stack needs one dark and one flat, not
twenty. **Recommendation:**

- When the stack starts (and when its setup changes) the service asks the
  library for the light group's matching darks (else bias) and flats with their
  own bias or dark flats; none found means no calibration (said in the state).
- The worker builds masters: median of up to 20 frames, read in strips from the
  files so no more than one strip of each is in memory; the flat minus its
  bias/dark, normalised per Bayer channel (so the flat's tint does not change
  the colour). Masters are stored at the stack's resolution (superpixel), cached
  as FITS under `<data>/masters/<hash of the frame ids>.fits` and reused across
  stacks and nights; they are internal (not in the catalog, not offered).
- Calibration happens after superpixel: exact for darks and bias (linear), and
  near exact for flats (vignetting and dust are smooth at 2 px).
- **No dark:** a cosmetic correction instead: per channel, pixels more than
  ~8σ above the median of their 3×3 neighbours are replaced by it (hot pixels
  walk across an undithered stack otherwise).
- The first frame waits for its masters (tens of seconds once, from the
  microSD); frames meanwhile are dropped as for a busy pipeline.

### D6. Display: stretch, preview, getting it to the phone

- **Stretch in the worker, from the linear stack**, after every frame: the
  pipeline's per-channel MTF stretch (unlinked, so it also neutralises the
  background colour), on the 1920 px downscale, JPEG 85 → a new
  `/api/previews/<uuid>.jpg` (immutable URL, the last few kept, like camera
  previews). Observers can see it: a stack is what EAA shows to visitors.
- **Look controls** (server-side, applied to the next render and re-rendered at
  once without a new frame, ~0.2 s): background level (the stretch's target,
  default 0.25), black clipping (shadows σ), saturation (a simple chroma boost),
  and a *linked* stretch toggle for frames already colour-balanced. Kept per
  device in the settings (ADR 0016), not per stack. Gradient removal is left for
  later.
- **State** under `stack`: `on`, `status` (idle, preparing, stacking, failed),
  `frames`, `rejected`, `exposure` (total seconds), `started`, `target`,
  `filter`, `calibration` (dark/flat used or why not), `last` (accepted or why
  not, shift in px, rotation, stars, seconds), `preview` (url, width, height,
  time), `look`. Small, as in ADR 0005: pixels never cross the state channel.
- No full-resolution view in v1 beyond *Save* (the saved JPEG is the full stack
  resolution, 3124 px, and can be opened from the night's frames).

### D7. Where it runs, and what a crash loses

| Option | For | Against |
|---|---|---|
| **The same imaging worker, stack state held by the worker process** | One process and its memory (ADR 0012); no pixel transfer; the preview and the stack read the same file one after the other | The stack waits behind previews and autofocus measures (seconds); a crash loses the stack |
| A second worker for stacking | Uses a second core; isolates a crash | Twice the baseline memory (~160–390 MB per process), a second pool to supervise; not needed at 30 s frames |

**Recommendation: the same worker.** A `ProcessPoolExecutor` with one worker
keeps module state between calls; the stack lives there, keyed by a stack id
that nocsd chooses, and every call says which stack it expects, so a restarted
worker answers "unknown stack" instead of adding to a stale one. When the
worker dies (or nocsd restarts) the stack is lost: the state says so and the
next frame starts a new one. Rebuilding from the saved subs (their ids are
known) is left for later.

The hook never makes a capture wait: the stack call runs in the background, at
most one frame waiting (a newer frame replaces it, counted as skipped), and for
unsaved loop frames the stacker takes over deleting the file.

### D8. Lifecycle: Live view, sequences, autofocus, dither, flips

- **One global switch** "stack frames as they arrive" (Live view, also shown in
  the Session monitor): it stacks main-camera **light** frames from Live view
  (series and loop) and from sequences alike. Off by default; it stays as set
  across restarts.
- **A new stack** starts by itself when the target, filter, exposure, gain,
  binning or frame size changes (the old one is saved first if it has ≥ 2
  frames, D9), and after 3 consecutive frames that do not register (the mount
  went elsewhere). *New stack* starts one by hand. Mono cameras: one stack per
  filter, the current filter's shown; LRGB combination is later.
- **Autofocus, solving, polar alignment, flats** never reach the stack (their
  frames are not lights through `_finish`, or are not lights).
- **Dither:** nothing to do; it is what lets sigma clipping remove hot pixels
  and walking noise. **Meridian flip:** registration takes the 180°.
- **Sequences** need no new instruction in v1; a *Stack* toggle in the template
  is possible later if the global switch proves too coarse.

### D9. Saving the stack

**Recommendation:** saved automatically when a stack ends (new stack, switch off,
end of sequence) with ≥ 2 frames, and on demand: a FITS (float32, linear,
`NAXIS3 = 3` for colour, headers: frames, total exposure, the reference's
pointing, filter, camera, calibration used, NOCS version; WCS when the reference
is solved) and a stretched full-size JPEG, in `<night>/Stack/<target>/`,
catalogued as frame type `stack` (catalog v7) so the night's list and zip
include them; the calibration library ignores them. ~78 MB per colour stack on
the drive.

### D10. Pi 5 budget and benchmark

Estimated per 26 MP colour frame, from this x86 (Core Ultra 7, measured with a
quick script) and the Pi/x86 ratios of the performance spike (×2–4):

| step | x86 (measured) | Pi 5 (estimate) |
|---|---|---|
| load FITS (already measured) | 36 ms | 140 ms |
| superpixel to 3124×2088 RGB float32 | 150 ms | 300–450 ms |
| calibrate (dark, flat) at half resolution | — | ~100 ms |
| stars (`sep` on 6.5 MP; the spike's 2×2 binned figure) | 250 ms | 500–550 ms |
| match + RANSAC | — | < 50 ms |
| `warpAffine` (bilinear, 3 channels) | 20 ms | 60–80 ms |
| Welford + rejection, strips | 100 ms | 300–400 ms |
| downscale, stretch, JPEG of the stack | ~80 ms | ~250 ms |
| **total** | **~0.65 s** | **~1.7–2 s** |

On top of the preview's ~1.4 s: ~3.5 s of the worker per 30 s frame. Memory in
the worker: accumulators ~0.2 GB, masters ~0.16 GB, transients ~0.3 GB at peak
(the raw frame, its float copy, the warped one): ≤ 0.7 GB above today's worker.
`dev/bench/stack_bench.py` (S2) measures each step on synthetic 26 MP Bayer
frames (and on the bench's simulator samples when present), median of N, so the
table above is replaced by numbers from the lab Pi in S7.

**Measured (S2)** with `dev/bench/stack_bench.py`, 8 synthetic 26 MP RGGB frames
with dithers and a flip, on this session's cloud VM (4 cores; slower than the
spike's PC: its preview takes 1.6 s against ~0.6 s there), median ms per frame
after the first:

| load | reduce (superpixel) | stars | register | warp | accumulate | render | **stack** | preview |
|---|---|---|---|---|---|---|---|---|
| 85 | 62 | 431 | 5 | 22 | 205 | 363 | **1245** | 1612 |

The stack costs ~0.8× the preview the worker already makes, so ~1.1–1.5 s on the
Pi; stack arrays 187 MB, peak RSS of a process doing both 1.13 GB (the preview's
full-resolution debayer included). The stars and the stretch in the render are
the largest steps: a lookup table for the stretch is the first saving to try if
the Pi needs one.

Possible saving if the Pi is slower than estimated: reuse the preview's star
detection (it already bins 2×2 on colour frames, i.e. superpixel resolution) by
doing preview and stack in one worker call that loads the file once.

## Testing

- **Synthetic frames** (`tests/synthstars.py`): Gaussian stars with a power-law
  flux distribution rendered on a Bayer mosaic (RGGB, per-channel colour) or
  mono, sky background, Poisson and read noise, hot pixels, optional vignetting,
  a satellite line, a known similarity transform per frame. Registration and
  stacking tests assert recovered transforms, SNR growth, rejection.
- **Simulators:** the CCD simulator with the GSC catalog, a series of frames
  with small mount moves between them (pulse guide or a go to a few arcseconds
  off), stacked through the API (`@pytest.mark.indi`).
- **Bench:** `dev/bench/stack_bench.py`, also runnable on the lab Pi.

## Notes

- Shared files kept small: `api/schemas.py` (the `stack` state and requests),
  generated types, `api/app.py` wiring, `imaging/capture.py` (one hook),
  `imaging/worker.py` (stack calls), Live view and the Session monitor.
- Later (not in this plan): LRGB/narrowband combination for mono, gradient
  removal, full-resolution and drizzle stacking, rebuilding a stack after a
  crash, weighting by noise, a stack per sequence target in the template,
  annotating objects on the stack from its WCS.
