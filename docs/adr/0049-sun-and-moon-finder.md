# 0049. The Sun and the Moon are found by their brightness, and the Sun needs a warning acknowledged

Date: 2026-11-15 · Status: Proposed

## Context

The maintainer wants NOCS to point at the Sun and the Moon and centre them, then
track them at their own rate. Facts:

- **Plate solving cannot help near them.** ASTAP needs stars; a frame with the Sun or
  the Moon in it is a bright disc on a bright (day) or flooded (night) sky.
- **NOCS knows where they are.** `nocs.sky.ephemeris` gives the Sun (ERFA `epv00`)
  and the Moon (`moon98`, with the site's parallax, up to a degree) to a few
  arcseconds, with their semidiameters. Their JNow coordinates follow from the
  topocentric altitude and azimuth (`nocs.mount.coords.horizontal_to_jnow`).
- **The mount does not know where it points, by day.** Solar observing happens with
  no polar alignment and no sync: the mount was levelled and pointed at the pole by
  eye, so a go to can miss by several degrees. A field of view is often a degree or
  two: the body may not be in the first frame.
- **A disc is easy to find in a frame, roughly.** Saturated or not, it is the largest
  bright region. With a 0.1 s exposure, the Sun behind a solar filter, the Moon at
  night and a daylight Moon all stand out; a daylight sky with no filter can saturate
  at 0.1 s and must be exposed shorter. Binning makes frames small and quick.
- **Its centre is not the centre of what is lit.** A crescent's light lies far from
  the disc's centre, and a disc at the frame's edge is cut. Its radius in pixels is
  known (semidiameter over the field of view) and its lit limb is an arc of that
  circle: a circle fit to the limb finds the centre in all these cases.
- **Without a solve, the camera's angle is unknown.** Moving the mount a known amount
  in RA and then in Dec and watching the disc move tells how sky offsets map to
  pixels (what PHD2's calibration does with a star).
- **INDI mounts offer lunar and solar tracking** (`TELESCOPE_TRACK_MODE`), which
  NOCS already shows and sets.
- **Pointing a telescope at the Sun without a proper filter blinds and burns.** An
  eye at the eyepiece or finder is damaged at once and for good; a camera's sensor
  and a filter wheel's filters can be ruined. Nothing in NOCS warned about it, and
  any go to could aim close to the Sun by day.
- **The rig's altitude limits** are the mount's own, which NOCS only shows; the lab's
  temporary 80° limit is gone. A NOCS maximum altitude is in the v1.0 backlog.

## Decision

### The Sun's warning

- **A go to within 20° of the Sun while the Sun is up** (its centre above −1°) is
  refused until the owner has acknowledged the Sun's warning. The refusal is a
  `PointingError` (409) that says "near the Sun"; `force` (below the horizon) does
  not lift it. It covers every go to of NOCS (go to, the zenith, go and centre,
  sequences, polar alignment, the finder), checked where the horizon is.
- **The warning says**: never look at the Sun through a telescope, a finder or a
  camera's viewfinder; only with a certified solar filter (ISO 12312-2 film or
  glass, or a solar telescope) that covers the whole aperture of the main telescope,
  and with the finder and the guide scope capped or filtered too; unfiltered
  sunlight burns eyes, sensors and filters in seconds.
- **The acknowledgment lasts a day**: until the site's local (mean solar) date
  changes, or nocsd restarts. `POST /api/mount/sun-warning` records it;
  `mount.sun_acknowledged` tells clients. A go to refused for it shows the warning,
  and acknowledging it goes on with the go to. Nothing withdraws it within the day
  (taking the solar filter off while the Sun is still up, say).
- **Finding the Sun stops PHD2** (looping or guiding): its guide camera would see
  the Sun through the guide scope. Other go tos near the Sun, once acknowledged, do
  not stop it, and PHD2 is not kept from looping there.
- The path a slew takes is not checked, only where it ends; nor are park, home and
  the pad's manual moves. Screens that run jobs (polar alignment, sequences) fail
  with the refusal's message and do not offer the warning themselves.

### The finder

`POST /api/finder` runs a `find` job (`nocs.finder`) for the Sun or the Moon, with
the main camera; it locks what centring locks. Its state is under `("finder",)`.

1. **Track the body** at its rate: lunar or solar when the mount offers it, else
   the mount's own (and the result says so). Tracking is switched on first, so the
   body stays put during the search. The rate it replaced comes back when the run
   fails or is cancelled, and after a run that succeeds, at the next go to that is
   not the finder's (`MountService.track_body`): a deep-sky target after the Moon
   must not track at the lunar rate. A rate the owner chooses is not put back.
2. **Search** with frames of a fixed exposure (0.1 s by default) at the camera's
   largest binning up to 4: at the body's ephemeris position, then along a square
   spiral of steps 0.7 of the field's short side, up to a radius (5° by default).
   Aims are offsets from the body's position at the time of each slew, so the body's
   motion does not add up. A frame without the disc whose background is above half
   the scale is taken again at a quarter of the exposure, down to 0.1 ms or the
   camera's shortest. Positions below the horizon are skipped, and so are those near
   the Sun before its warning is acknowledged (a daylight Moon); the failure says how
   many. A search of more than 2000 positions is refused. Each frame is the main
   camera's preview, so Live view shows the search.
   "From here" centres the spiral where the mount points instead: the owner can stop
   the finder, bring the body near with the pad (for the Sun, by making the tube's
   shadow smallest) and start it again from there.
3. **Find the disc** in the imaging worker: the largest region above halfway between
   the background and the brightest pixels, of an area that fits the expected disc;
   a circle of the expected radius (±25 %) fitted to its edge away from the frame's
   border (RANSAC, then least squares), whose centre has the region inside. The
   frame is reduced to 640 px first; discs under 4 px of radius there take the
   region's centroid. A frame filled by the disc has
   no limb to fit, so the finder refuses a field whose short side is less than the
   disc's diameter over 0.9.
4. **Calibrate**: move a quarter of the field's short side east, then north (the
   other way when the disc leaves the frame), and measure how the disc moved: a
   2×2 matrix from sky offsets to pixels. Moves that do not move the disc as the
   plate scale says fail the run, and so does a pier side flip during the run (near
   the meridian), which turns the camera.
5. **Centre**: aim so the disc's centre lands on the frame's centre, until within the
   tolerance (2′ by default), 6 attempts at most.
6. **Sync** the mount to where it then points (on by default): the body's position,
   less what is left of the centring. By day it has nothing better to point by.

### Backlog

Lunar and solar guiding (keeping the disc where the finder left it) and a daytime
polar alignment from finder runs are in the v1.0 roadmap.

## Consequences

- The Sun can be found only with the warning acknowledged that day; before that, a
  Moon near the Sun (a thin crescent by day) is searched for only away from it.
- Searching takes time: a 5° spiral with a 1° field is ~200 positions, several
  seconds each. The pad and "from here" are the quick way when the error is large.
- The finder needs the main camera's field (focal length in the profile) and a mount
  that slews; it fails on a frame where something else is brighter (a planet in a
  wide field at night, a lit building).
- Eclipses and a Moon only a day or two from new fit badly; they are not handled.
- Tests: synthetic frames (discs, crescents, cut discs, daylight backgrounds, stars)
  for the detection, and fakes for the search, calibration and centring; the
  simulators draw no Sun or Moon.
