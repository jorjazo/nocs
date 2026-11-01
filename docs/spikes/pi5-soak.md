# Spike: a whole night on the Raspberry Pi 5 (soak test)

Date: 2026-11-01 · Status: **running** (results follow when the 8 h run on the Pi ends) · Related:
[Pi 5 performance](pi5-performance.md), [ADR 0012](../adr/0012-image-pipeline.md),
[ADR 0030](../adr/0030-supervision.md), [ADR 0031](../adr/0031-sequences.md),
[ADR 0032](../adr/0032-sequence-recovery-and-restarts.md), [ADR 0033](../adr/0033-meridian-flip.md)

## Questions

v0.1 promises a full night from a phone on a Pi 5 (8 GB, microSD). Before the field test:

1. Does anything grow through a night: memory, open files, processes, CPU?
2. Do the Pi's temperature, supply or storage get in the way?
3. Does nocsd stay responsive (event loop, WebSocket patches) while it images all night?
4. What ends a night first?

## The tool

[`dev/tools/soak/run.sh`](../../dev/tools/soak/run.sh) brings up its own simulators
(compose project `nocs-soak`: INDI on 27624, PHD2 on 24400), its own nocsd on
127.0.0.1:28000 with config and data in the results directory and no nocs-system, runs
[`soak.py`](../../dev/tools/soak/soak.py) and writes `summary.md`. It never meets the
dev stack or, on the lab Pi, `indiserver@`, `phd2@` and `nocsd@jorjazo`, so it needs no
lab lock.

```sh
HOURS=2 EXPOSURE=5 dev/tools/soak/run.sh                         # PC, compressed
HOURS=8 EXPOSURE=30 ASTAP=/opt/astap/astap_cli dev/tools/soak/run.sh   # lab Pi
```

`SIGTERM` or Ctrl-C stops the night as a user would (end container: park, warm) and still
writes the summary.

**The night** is one sequence through the API: cool to −10 °C, unpark, centre on a field
at Dec −65° that starts half an hour east of the meridian, guide (PHD2), autofocus, then
Red, Green and Blue in batches of five until the time is up, with the triggers of a real
night: autofocus on a 1 °C change (the focuser simulator cools 1 °C an hour) and every
hour, a dither every 3 frames, a pointing check every 10, and a meridian flip 5 minutes
past the meridian. Frames are 26 MP, 52 MB (the reference rig's 6248×4176 sensor) at
1000 mm, so autofocus has a V-curve and ASTAP solves 1.3°×0.9° fields.

**The phone** is a WebSocket client that applies the snapshot and every patch, checks
that versions follow on, stays 2–15 minutes and sleeps 1–60 s before reconnecting
(resuming from its version; every fourth time from scratch, as a reopened app), posts its
clock on connecting and every 30 s, downloads every preview and every 10th FITS.

**Recorded** every 30 s, as JSON lines: resident memory, open descriptors, threads and
CPU of nocsd, its imaging worker and other children, and of every process in the INDI
and PHD2 containers (drivers by name); CPU temperature, cpufreq throttling, the Pi's
under-voltage alarm and `vcgencmd get_throttled`; load, available memory, free space and
writes of the frames' drive (`/proc/diskstats`) and nocsd's own `write_bytes`; the
latency of `GET /api/health` once a second (the event loop's), and how long a clock
report takes to come back as a patch; WARNING, ERROR and tracebacks in nocsd's log.
Frame files beyond the newest 60 are deleted as the night goes (the catalog keeps them)
so a compressed night does not fill the drive; bytes written still count.

Simulator settings the tool makes: the guide simulator's seeing goes to 8″ (at the
guide scope's 4.1″/px its default 3.5″ stars are under a pixel and PHD2 keeps losing
them, "low HFD").

## Results

### PC, compressed (2 h, 5 s frames)

Intel Core Ultra 7 255H, NVMe, shared with other work. Full data:
[results/pc-compressed](../../dev/tools/soak/results/pc-compressed/summary.md).
651 light frames (318/h; 220 Red, 216 Green, 215 Blue), 217 dithers, 64 pointing checks,
one meridian flip at +5 min (centred to 0.03′, PHD2 calibrated again), two autofocus runs;
**no failure**, the run ended `completed`, parked and warm.

| process | RSS start → end (MB) | max | fds | CPU % mean / p95 |
|---|---|---|---|---|
| nocsd | 198 → 204 | 204 | 30–32 | 1.8 / 2.2 |
| imaging worker | 203 → 238 | 391 (autofocus) | 11 | 4.6 / 6.0 |
| PHD2 | 214 → 213 | 215 | 22 | 1.7 / 2.0 |
| indiserver | 6 → 6 | 6 | 22 | 0.4 / 0.4 |
| CCD simulator | 72 → 72 | 72 | 5 | 4.3 / 6.1 |

- No growth: every process ends within a few MB of where it started (least-squares
  slopes −5 to +4 MB/h, noise around frame and autofocus peaks); descriptors flat.
- `/api/health`: median 1.7 ms, worst p99 18 ms; a clock report reaches the phone as a
  patch in 2.4 ms (max 32 ms). 15 WebSocket connections (4 from scratch), **no version
  gap**, every preview (644) and every 10th FITS downloaded, no failure.
- Nothing at WARNING or above in nocsd's log.

## What the soak found, and what was fixed

Each of the first three ended or would have ended a night; the fixes are on `main` with tests.

1. **Nights ended six minutes after the meridian flip** (PC and Pi alike). PHD2 turned
   its calibration's RA for the side the simulator reports, but Dec guiding then ran
   away (0.2 → 23 px in 20 s), no dither settled, and after four tries the guiding
   policy ended the session. Whether Dec must be reversed after a flip depends on the
   mount, so guiding now **calibrates again after every flip** (a few minutes, once a
   night) instead of `flip_calibration`. Afterwards guide steps stay under 0.25 px and a
   dither settles in 20 s ([ADR 0033](../adr/0033-meridian-flip.md), dated note).
2. **A single lost guide frame threw away the sub**, and three in a row end the night
   under the default guiding policy: with 30 s frames on the Pi, one frame in two
   failed. A frame now fails when its star was lost in more than 10 % of its guide
   frames ([ADR 0032](../adr/0032-sequence-recovery-and-restarts.md), dated note).
3. **Guiding restarted right after a stop failed** ("PHD2 stopped looping"): PHD2 says
   guiding stopped, then 3 ms later that its loop stopped too; NOCS took the first as the
   end of the stop, and the second reached the next start. A stop from guiding now waits
   for both (the tests' fake PHD2 sends both, as PHD2 does).

Measured, not changed:

4. **The WebSocket carries ~24 patches/s, ~19 kB/s per client (~70 MB an hour)**, and
   ~88 % of it is the raw INDI property mirror (`indi.devices`: the Telescope Simulator
   50 operations/s, the guide and main cameras 26 and 20), which only the developer
   screen (`#/dev`) shows. Harmless on a LAN; worth coalescing (one update per property
   per second) or sending only to clients that ask, for phones on weak Wi-Fi and for
   the Pi's JSON encoding with several clients.
5. **Guide frames do not wear the microSD.** nocsd writes every frame PHD2 takes (one
   every 2 s, 2.6 MB here) to `incoming/` for its preview and deletes it a second later:
   its `write_bytes` reads ~1 MB/s, but the card saw ~0.1 MB/s while guiding without main
   frames, as the files are gone before writeback.
6. **Simulator limits, not NOCS's:** the guide simulator's default 3.5″ stars are under
   a pixel at the guide scope's 4.1″/px and PHD2 keeps losing them ("low HFD"; still
   ~21 % of guide frames at 8″), so the tool sets 14″. PHD2 calibrates in ~4.5 min on
   the simulators.

## What limits a night

Memory, CPU and descriptors do not: nothing grows, and nocsd, its worker, PHD2 and the
drivers stay under ~800 MB together on an 8 GB Pi. **Storage does.** A 26 MP frame is
52.2 MB, and the storage service stops saving 1 GiB before the drive is full:

| free on the drive | frames | 60 s subs | 180 s subs | 300 s subs |
|---|---|---|---|---|
| 13 GB (the lab Pi's 32 GB card today) | ~230 | ~4.5 h | ~12 h | ~20 h |
| 50 GB (64 GB card) | ~940 | a night | a night | a night |

(hours of imaging at ~10 s overhead per frame plus a dither every 3 frames). Short subs
on a small card fill it before dawn: the builder's disk estimate should be heeded, or
frames go to a USB drive (ADR 0013).
