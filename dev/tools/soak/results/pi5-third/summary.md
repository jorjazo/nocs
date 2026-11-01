# Soak: pi5-20261101-0957

2026-11-01T12:58:30.143+00:00 → 2026-11-01T13:39:03.312+00:00 (0.68 h, 82 samples); slopes after the first 10 min.

## Processes

| process | n | RSS start → end (MB) | max | slope MB/h | fds start → end | max | CPU % mean / p95 |
|---|---|---|---|---|---|---|---|
| indi/indi_simulator_ccd | 1 | 75 → 75 | 75 | 0.0 | 5 → 5 | 5 | 3.1 / 8.0 |
| indi/indi_simulator_focus | 1 | 15 → 15 | 15 | 0.0 | 3 → 3 | 3 | 0.0 / 0.0 |
| indi/indi_simulator_guide | 1 | 25 → 25 | 25 | 0.0 | 4 → 4 | 4 | 3.0 / 3.7 |
| indi/indi_simulator_telescope | 1 | 16 → 16 | 16 | 0.0 | 3 → 3 | 3 | 0.1 / 0.1 |
| indi/indi_simulator_wheel | 1 | 17 → 17 | 17 | 0.0 | 3 → 3 | 3 | 0.0 / 0.0 |
| indi/indiserver | 1 | 8 → 8 | 8 | 0.0 | 22 → 22 | 22 | 0.8 / 1.0 |
| nocsd | 1 | 156 → 160 | 171 | 18.0 | 33 → 31 | 34 | 9.0 / 64.7 |
| nocsd/cat | 1 | 6 → 6 | 6 | 0.0 | 5 → 5 | 5 | 0.0 / 0.2 |
| nocsd/resource_tracker | 1 | 20 → 20 | 20 | 0.0 | 4 → 4 | 4 | 0.0 / 0.0 |
| nocsd/worker | 1 | 197 → 197 | 367 | -45.6 | 11 → 11 | 12 | 9.0 / 13.0 |
| phd2/Xvfb | 1 | 24 → 24 | 24 | 0.0 | 9 → 9 | 9 | 0.4 / 0.5 |
| phd2/phd2.bin | 1 | 239 → 239 | 239 | 0.0 | 22 → 22 | 22 | 3.9 / 4.6 |

## The computer

- CPU temperature: 54.5 – 63.4 °C, mean 57.7
- throttled (cpufreq): False; under-voltage: False; vcgencmd get_throttled: 0x0
- load average (1 min): mean 0.72, max 1.79
- available memory: 6.46 GB at least
- storage free: 12.6 → 10.0 GB (frames pruned meanwhile: 0)
- nocsd wrote 2.6 GB (1.04 MB/s)
- the frames' drive took 2.8 GB of writes (1.14 MB/s)

## nocsd and the phone

- frames: 49 (72/h), 2.6 GB, 52.2 MB each
- `/api/health` latency (≈ event loop): p50 of windows 3.6 ms, worst p99 43.3 ms, max 43.3 ms; failures 0
- patch lag (clock posted → patch on the WebSocket): median 5.4 ms, max 96.8 ms; probes without a patch 1
- WebSocket: 6 connections (2 snapshots), 0 failures, 0 version gaps, 61496 patches (17.5 kB/s); slowest connection 28.7 ms
- downloads: 49 previews (slowest 29.0 ms), 4 FITS; 0 failures

## Log

- nothing at WARNING or above

## The session report

```
{
 "filters": [
  {
   "filter": "Red",
   "frames": 19,
   "integration": 570.0,
   "clouds": 0,
   "hfr": 2.441,
   "guide_rms": 0.415
  },
  {
   "filter": "Green",
   "frames": 15,
   "integration": 450.0,
   "clouds": 0,
   "hfr": 2.443,
   "guide_rms": 0.418
  },
  {
   "filter": "Blue",
   "frames": 15,
   "integration": 450.0,
   "clouds": 0,
   "hfr": 2.441,
   "guide_rms": 0.412
  }
 ],
 "failures": 0,
 "events": {
  "started": 1,
  "action": 39,
  "frame": 49,
  "trigger": 21,
  "ending": 1,
  "ended": 1
 }
}
```
