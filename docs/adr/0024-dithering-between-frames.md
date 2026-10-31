# 0024. Dithering and settling between frames

Date: 2026-10-31 · Status: Proposed

## Context

Dithering moves the guide star's lock position by a few pixels between frames, so
that fixed sensor patterns (hot pixels, walking noise) fall on different sky
positions and stacking removes them. PHD2 does the move and then waits until the
star has settled (`dither` with `settle`, then `SettleDone`, ADR 0006). NOCS has
to decide when to dither, by how much, what to do when settling fails, and how
the sequencer (phase 5) will use it. Facts:

- PHD2's `dither` amount is in guide camera pixels. What matters for stacking is
  the move on the main camera, whose pixel scale is different (an OAG or a
  built-in guide sensor shares the focal length but not the pixel size; a guide
  scope differs in both).
- On the simulators (1 s exposures), a 5 px dither settles in ~10 s with
  `{pixels: 1.5, time: 5}`. `SettleDone.Status` is non-zero when the timeout
  ran out; PHD2 goes on guiding.
- Phase 2's capture takes one frame per request; the sequencer will run frames
  and dithers inside its own job, which holds the main camera and, for slews, the
  mount (phase 5 plan).
- PHD2 stamps every guide step; nocsd and PHD2 share the system clock (the same
  host, or the same kernel in development). NOCS's own clock may be corrected
  from a client (ADR 0015), PHD2's never is.

## Decision

- **Amounts are main camera pixels.** NOCS converts them with both trains'
  pixel scales: the main camera's from its optics, pixel size and binning
  (`cameras.main_camera.field.scale`), the guide camera's as PHD2 reports it.
- **Dithering runs inside the caller's job.** `GuidingService.dither(context, …)`
  sends the dither and returns once PHD2 has settled; `start(context, …)` starts
  guiding the same way. When the caller's job holds the mount (a sequence),
  guiding does not reserve it: that job must stop guiding before it slews. A
  paused sequence lends its locks; `guide_under(job)` hands the mount back from
  guiding's own hold before it resumes.
  `POST /api/guiding/dither` runs a dither as a job of its own.
- **A series of frames dithers between them.** An exposure request takes a
  `count` and a `dither` plan (every n-th frame, pixels, settle, RA only). The
  series is one job; before every n-th frame after the first, while PHD2 guides,
  it dithers and waits for settling. A dither that does not settle, or a PHD2
  that does not guide, is a warning in the job's result, and the series goes on:
  the next frame shows by its guiding figures whether it is any good.
- **Every saved main frame records how guiding went**: the RMS in RA, Dec and
  total (arcseconds), the guide steps and the frames without the star, over the
  steps PHD2 stamped between the start and the end of the exposure (system
  clock). They go to the frame catalog and to the frame list.

## Consequences

- The same dither means the same move on the sky whatever the guiding train:
  the default, 5 main camera pixels, is 4.7 guide pixels for the lab Duo
  (3.76 µm main and 4 µm guide pixels through the same 380 mm), and 2.5 for a
  2.4 µm guide camera on a 120 mm guide scope.
- The sequencer reuses the series' pieces (dither and start in its own job)
  instead of driving PHD2 itself, and gets per-frame guiding figures for its
  quality rules and the session report.
- A failed settle never stops a night: frames taken anyway carry their RMS, and
  rules on bad frames belong to the sequencer (phase 5).
- The catalog gains five columns on frames (schema version 3); frames saved
  before have none.
