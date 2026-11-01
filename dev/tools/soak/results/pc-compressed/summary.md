# Soak: pc-compressed

2026-11-01T06:52:02.117+00:00 → 2026-11-01T08:52:55.531+00:00 (2.02 h, 86 samples); slopes after the first 10 min.

## Processes

| process | n | RSS start → end (MB) | max | slope MB/h | fds start → end | max | CPU % mean / p95 |
|---|---|---|---|---|---|---|---|
| indi/indi_simulator_ccd | 1 | 72 → 72 | 72 | -0.1 | 5 → 5 | 5 | 4.3 / 6.1 |
| indi/indi_simulator_focus | 1 | 16 → 16 | 16 | -0.1 | 3 → 3 | 3 | 0.0 / 0.0 |
| indi/indi_simulator_guide | 1 | 22 → 22 | 22 | -0.1 | 4 → 4 | 5 | 1.1 / 1.3 |
| indi/indi_simulator_telescope | 1 | 17 → 17 | 17 | -0.1 | 3 → 3 | 3 | 0.0 / 0.1 |
| indi/indi_simulator_wheel | 1 | 16 → 16 | 16 | -0.1 | 3 → 3 | 3 | 0.0 / 0.0 |
| indi/indiserver | 1 | 6 → 6 | 6 | 0.0 | 22 → 22 | 22 | 0.4 / 0.4 |
| nocsd | 1 | 198 → 204 | 204 | 4.4 | 32 → 30 | 32 | 1.8 / 2.2 |
| nocsd/resource_tracker | 1 | 15 → 15 | 15 | -0.0 | 4 → 4 | 4 | 0.0 / 0.0 |
| nocsd/worker | 1 | 203 → 238 | 391 | -4.9 | 11 → 11 | 11 | 4.6 / 6.0 |
| phd2/Xvfb | 1 | 24 → 26 | 26 | 1.7 | 9 → 9 | 9 | 0.1 / 0.1 |
| phd2/phd2.bin | 1 | 214 → 213 | 215 | 0.9 | 22 → 22 | 22 | 1.7 / 2.0 |

## The computer

- CPU temperature: 50.0 – 70.0 °C, mean 53.8
- throttled (cpufreq): False; under-voltage: False; vcgencmd get_throttled: not available
- load average (1 min): mean 0.65, max 1.64
- available memory: 20.55 GB at least
- storage free: 150.2 → 123.3 GB (frames pruned meanwhile: 591)
- nocsd wrote 8.4 GB (1.16 MB/s)
- the frames' drive took 36.3 GB of writes (4.98 MB/s)

## nocsd and the phone

- frames: 644 (318/h), 33.6 GB, 52.2 MB each
- `/api/health` latency (≈ event loop): p50 of windows 1.7 ms, worst p99 17.7 ms, max 18.6 ms; failures 0
- patch lag (clock posted → patch on the WebSocket): median 2.4 ms, max 32.1 ms; probes without a patch 1
- WebSocket: 15 connections (4 snapshots), 0 failures, 0 version gaps, 191046 patches (19.4 kB/s); slowest connection 30.3 ms
- downloads: 644 previews (slowest 39.2 ms), 64 FITS; 0 failures

## Log

- nothing at WARNING or above

## The session report

```
{
 "filters": [
  {
   "filter": "Red",
   "frames": 220,
   "integration": 1100.0,
   "clouds": 0,
   "hfr": 2.397,
   "guide_rms": 0.1915
  },
  {
   "filter": "Green",
   "frames": 216,
   "integration": 1080.0,
   "clouds": 0,
   "hfr": 2.398,
   "guide_rms": 0.1885
  },
  {
   "filter": "Blue",
   "frames": 215,
   "integration": 1075.0,
   "clouds": 0,
   "hfr": 2.398,
   "guide_rms": 0.167
  }
 ],
 "failures": 0,
 "events": {
  "started": 1,
  "action": 422,
  "frame": 651,
  "trigger": 283,
  "condition": 1,
  "ending": 1,
  "ended": 1
 }
}
```
