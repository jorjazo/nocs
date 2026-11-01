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
