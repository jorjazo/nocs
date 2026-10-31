# 0018. Plate solving with ASTAP

Date: 2026-10-31 · Status: Proposed

## Context

ADR 0006 chose ASTAP's command-line solver. Phase 3 needs it for solve and sync and
for centring, and phases 4 and 5 will reuse it for polar alignment, re-centring and
the meridian flip. Facts measured before deciding how to call it:

- **Speed.** On the lab Pi 5 with the D50 database, the maintainer's frames (26 and
  61 MP, and a 2 MP one at 1000 mm) solve near a hint in 0.45–2.7 s wall time,
  ASTAP included; the spike measured ~4 s for the whole sky with a known field
  ([spike](../spikes/pi5-performance.md)). On a laptop, 0.2–1.2 s.
- **Databases.** ASTAP's compact databases solve fields up to 6° high: D80 from
  0.15°, D50 from 0.2°, D20 from 0.3°, D05 from 0.6°; G05 covers 3–20°, W08 20–80°.
  D05 is ~100 MB, D50 ~900 MB. D05 failed every dense Milky Way frame of the
  maintainer's (M 16 in Hα, Sgr A* at 394 mm, 3.6° field) that D50 solved.
- **Downsampling** (`-z`) must follow the star size and the frame size. ASTAP's
  automatic choice (`-z 0`) bins the simulators' sharp stars (HFR ~0.5 px) out of
  existence. Real frames: a sharp 26 MP frame (HFR 1.8 px) solves at `-z 1` or
  `-z 2`; a badly defocused 61 MP one (HFR 22 px) only at `-z 2` or `-z 3`; a
  1920 × 1080 frame of ω Centauri (HFR 4.4 px, the cluster filling a 0.36° field)
  only at `-z 1`.
- **Search speed.** `-speed slow` overlaps ASTAP's search steps more. Near a hint it
  cost nothing measurable on any frame tried and solved three that the default
  missed (ω Centauri, the defocused frame at `-z 3`, a sparse simulator frame);
  over the whole sky it took about twice as long on an easy frame (0.6 s instead of
  0.3 s) and found ω Centauri in 42 s where the default gave up after 27 s.
- **The simulators** render the catalog at the mount's position (solutions within
  0.06′) and rotate the frame with `SIM_ROTATION`. With D05, about half their 2 s
  frames had too few stars above the noise to solve; every 5 s frame solved.
- **Positions.** Solutions are ICRS (J2000). Without `-ra`/`-spd`, ASTAP starts its
  whole-sky search from the RA/DEC in the FITS header, if any.
- **Rotation.** ASIAIR records the camera angle it solved (`ROTATOR`): on five of
  the maintainer's frames, from two cameras and two mounts, it is 360° minus the
  position angle of the top of the image as shown, within 1°.
- ASTAP writes its result (`.ini`, `.wcs`) next to the image unless told a base
  name with `-o`, and exits 1 (no solution), 2 (not enough stars), 16 (unreadable
  image) or 32/33 (database missing or unreadable).

## Decision

- **One ASTAP process per solve**, run with anyio and killed on timeout or when the
  caller is cancelled. The frame is read where it is; the result goes to a
  temporary directory (`-o`), so frames are never copied nor written next to.
- **One solve at a time** in nocsd (a lock in `SolverService`), since each solve
  uses every core of the Pi for a moment.
- **Discovery:** `NOCS_ASTAP` and `NOCS_ASTAP_DB`, else `astap_cli` on the PATH or
  in `/opt/astap` (where its packages install it), with the databases next to it.
  The state (`solver`) says whether ASTAP is there, its version and which databases
  are installed with the fields they solve; a frame whose field no installed
  database covers is refused with that reason rather than left to time out.
- **Hints:** the frame's height in degrees comes from the optical train, the sensor,
  the binning and the region (`cameras.<role>.field`, computed by the server so the
  solver, the framing and the UI agree); the position from the mount, converted
  from JNow to J2000 (ADR 0015), searched within 10°. Without a solution there, the
  whole sky is searched with the same field (`-r 180`), unless the caller asks not
  to.
- **Downsampling from the measured stars and the frame:** the largest factor (1 to
  3) that keeps a star's half-flux diameter at 3 px or more, from the HFR the
  imaging worker measures (ADR 0012), and leaves at least 1500 rows per step; 1 when
  no HFR is known.
- **Always `-speed slow`.**
- **A solution** is the J2000 centre of the frame, the scale, the position angle of
  the top of the image as NOCS shows it (honouring `ROWORDER`), whether the view is
  mirrored, and the WCS for the corners. Callers convert to JNow for the mount at
  the frame's mid-exposure time.
- **Timeouts:** 30 s near a hint, 120 s for the whole sky.
- **Development and CI** install the command-line solver and D05 with
  `dev/astap/install.sh` into `dev/.astap` (CI caches it: SourceForge serves it at
  ~200 kB/s). D05 covers the simulators as the tests set them up (5 s exposures).
  Tests on real
  frames (`NOCS_TEST_FRAMES`) run where D50 is installed: the lab Pi, or a laptop
  with a copy. **The appliance ships D50** (phase 6 image), as the spike already
  assumed.

## Consequences

- Solve and sync, centring, polar alignment and re-centring share one tested call:
  `SolverService.solve(frame, fov=…, hint=…, hfr=…)`.
- A field over 6° high (short lenses) needs G05 or W08 installed; NOCS says so
  instead of failing slowly.
- The rotation NOCS shows runs the opposite way from ASIAIR's camera angle; the UI
  must say which way to turn the camera rather than show bare angles.
- On a Pi with only D05 (smaller image), dense Milky Way fields will not solve.
