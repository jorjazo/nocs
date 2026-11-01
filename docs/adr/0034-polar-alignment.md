# 0034. Polar alignment from three solved frames

Date: 2026-11-01 · Status: Proposed

## Context

A mount's RA axis has to point at the celestial pole for tracking to follow the
sky; the error shows as drift that guiding has to chase and as field rotation.
The lab's site is at latitude −30°, where no star marks the pole, so the method has
to work from plate solves alone, in both hemispheres (roadmap, phase 4). Facts:

- Phase 3 solves a frame of the main camera with ASTAP and the D50 database
  (ADR 0018); `PointingService.solve_frame` runs inside any job holding the camera
  and the mount. A raw colour frame needs ASTAP's downsampling of at least 2.
- The AM5/AM7 add every sync to their own alignment model, and undo a sync near
  home and the pole (phase 3). They do not always report the pier side (ADR 0015).
- The INDI telescope simulator has a pointing model, `MOUNT_MODEL`, whose `MM_ME`
  and `MM_MA` (arcminutes, ±300) are polar axis errors in elevation and azimuth:
  the CCD simulator renders the sky where a mount with that error would point
  (`EQUATORIAL_PE`). Measured at Diaguitas: `MM_ME` +60′ fits as the axis 60.0′
  above the south pole, `MM_MA` +60′ as 60.0′ east of it; `MM_MA` is an angle on
  the sky, not in the horizon. A go to at the same Dec leaves the simulator's Dec
  axis (`MOUNT_AXES`) where it was, and it changes pier side only across the meridian.
- With three frames 30° apart in RA, an error of 1″ in each solve's position puts
  the fitted axis ~9″ (rms) off; with 10° steps ~80″, with 45° ~4″. More frames on
  the same arc barely help (`nocs.align.polar`, simulated).
- After the three frames, the knobs can be read from the frame's moves only where
  the altitude and the azimuth knob move it in different directions: not near the
  zenith, nor due east or west. Best is the meridian on the pole's side of the
  zenith.

## Decision

- **Three-point method on the main camera, never syncing.** Solve, turn the RA axis
  30°, solve, turn 30° more, solve. Turning the RA axis carries the camera around it,
  so the three directions lie on a circle about the axis: the axis is the normal of
  the plane through them. The job never syncs the mount: the method needs only the
  solutions, and the AM5's own model is left alone.
- **Directions in the site's equatorial frame of the date**, fixed to the Earth: a
  solution (J2000) is taken to JNow at mid-exposure and to its hour angle with the
  local apparent sidereal time (ERFA). The error is against the **true pole of the
  date, without refraction** (at 30° of altitude it shows the pole ~1.7′ higher; a
  later option). It is reported in words that hold in both hemispheres: altitude
  (positive: the axis points above the pole) and azimuth on the sky (positive: the
  axis points east of it), and their total.
- **The RA axis turns away from the meridian**, so the mount never flips between the
  points; the side is decided from the hour angle, not from `TELESCOPE_PIER_SIDE`.
  The turn is a go to at the mount's own Dec and its RA plus 2 h (or minus, to the
  east). The fitted rotation between the points is checked against the turn asked
  for: a Dec axis that moved shows there.
- **Where to start.** The job refuses a start whose points would fall under the
  horizon profile or the mount's lower limit, within 10° of the pole (the circle is
  then not much larger than the field, and that is where the mounts park), or whose
  last point reads the knobs poorly (sensitivity under 0.2: a solve's error would
  grow more than five times in the knobs). The app suggests a start on the meridian
  halfway between the zenith and the pole (Dec −60° at the lab's site).
- **Following the knobs.** At the last point the job exposes and solves again and
  again, tracking. The knobs turn the whole mount: the altitude knob about a
  horizontal line square to the axis, the azimuth knob about the vertical. Each frame
  is compared with the previous one, after the tracking between them about the
  current axis, to tell how far each knob was turned; the axis moves by as much.
  Chaining frames makes the solves' noise add up slowly but cancels slow tracking
  errors (periodic error) between the first frame and the last.
- **Ending.** Finishing goes back to the start (unless asked not to); cancelling
  stops where it is, since a cancel may be for safety (a cable caught).
- **Tolerance** 1′ by default for "aligned".
- The math lives in `nocs.align.polar`, pure functions of directions, so tests run
  without a mount; the job (`polar_align`) and its state come in stage 4.9.

## Consequences

- Polar alignment needs a solving frame away from the pole; it works the same in
  the north and the south, with or without a pole star in view.
- With 3″ solves the fitted axis is ~0.5′ off (rms): the 1′ tolerance is near what
  the method can tell. The live phase's trend smooths the readout, not the fit's
  offset; a fourth point or longer turns are the way to improve it if the field
  shows it matters.
- Correcting the error for refraction, a motorised corrector (INDI's simulator
  already snoops an "Alignment Correction Simulator"), and a start chosen from the
  horizon profile are left for later.
- The lab has to confirm on the AM7 that a go to at its own Dec turns only the RA
  axis, with syncs in its model; if the Dec axis moves, the turn becomes a timed
  `MOTION_WE` at a known rate, and the measured rotation is used as it is.
- Tests use the simulator's `MOUNT_MODEL` as a misaligned mount and change `MM_ME`
  mid-run as the user turning the altitude knob; they must clear it after. Its
  `MM_MA` moves the pole east without the turn about the polar axis that a real
  azimuth knob (a turn about the vertical) also brings, so it stands for the azimuth
  error but not for turning that knob: the knob is tested against the fakes.
- One frame's move gives two numbers for two knobs: nothing is left over to tell a
  bad frame from a knob turn. The frame's rotation (from the solve) would be a third.
