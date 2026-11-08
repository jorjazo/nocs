# Soak: nocs-soak-20261102-1916

2026-11-02T22:23:58.654+00:00 → 2026-11-03T06:25:05.130+00:00 (8.03 h, 961 samples); slopes after the first 10 min.

## Processes

| process | n | RSS start → end (MB) | max | slope MB/h | fds start → end | max | CPU % mean / p95 |
|---|---|---|---|---|---|---|---|
| indi/indi_simulator_ccd | 1 | 75 → 74 | 126 | -0.1 | 5 → 5 | 7 | 4.2 / 8.4 |
| indi/indi_simulator_focus | 1 | 15 → 14 | 15 | -0.0 | 3 → 3 | 3 | 0.0 / 0.0 |
| indi/indi_simulator_guide | 1 | 28 → 26 | 28 | -0.1 | 4 → 4 | 5 | 3.3 / 3.6 |
| indi/indi_simulator_telescope | 1 | 16 → 15 | 16 | -0.1 | 3 → 3 | 3 | 0.1 / 0.1 |
| indi/indi_simulator_wheel | 1 | 16 → 14 | 16 | -0.1 | 3 → 3 | 3 | 0.0 / 0.0 |
| indi/indiserver | 1 | 9 → 9 | 11 | -0.0 | 22 → 22 | 23 | 0.9 / 0.9 |
| nocsd | 1 | 168 → 202 | 202 | 1.9 | 33 → 31 | 35 | 4.3 / 5.5 |
| nocsd/astap_cli | 1 | 109 → 108 | 214 | 2.6 | 7 → 8 | 8 | 1.7 / 3.4 |
| nocsd/cat | 1 | 6 → 6 | 6 | -0.0 | 5 → 5 | 5 | 0.0 / 0.0 |
| nocsd/resource_tracker | 1 | 21 → 21 | 21 | -0.0 | 4 → 4 | 4 | 0.0 / 0.0 |
| nocsd/worker | 1 | 208 → 183 | 378 | -2.0 | 11 → 11 | 13 | 10.1 / 12.6 |
| phd2/Xvfb | 1 | 24 → 23 | 24 | -0.0 | 9 → 9 | 9 | 0.3 / 0.4 |
| phd2/phd2.bin | 1 | 242 → 241 | 242 | -0.0 | 22 → 22 | 22 | 4.1 / 4.4 |

## The computer

- CPU temperature: 46.3 – 54.5 °C, mean 49.3
- throttled (cpufreq): False; under-voltage: False; vcgencmd get_throttled: 0x0
- load average (1 min): mean 0.44, max 2.13
- available memory: 6.79 GB at least
- POSIX semaphores in /dev/shm: 5 → 5 (max 5); nocsd's children: 4 at most
- storage free: 21.2 → 18.0 GB (frames pruned meanwhile: 714)
- nocsd wrote 35.0 GB (1.21 MB/s)
- the frames' drive took 42.5 GB of writes (1.47 MB/s)

## nocsd and the phone

- frames: 772 (96/h), 40.3 GB, 52.2 MB each
- `/api/health` latency (≈ event loop): p50 of windows 3.7 ms, worst p99 58.5 ms, max 58.5 ms; failures 0
- patch lag (clock posted → patch on the WebSocket): median 4.9 ms, max 137.3 ms; probes without a patch 2
- WebSocket: 52 connections (14 snapshots), 0 failures, 0 version gaps, 358314 patches (4.2 kB/s); slowest connection 29.8 ms
- downloads: 772 previews (slowest 183.7 ms), 77 FITS; 0 failures

## Log

- nothing at WARNING or above

## The session report

```
{
 "filters": [
  {
   "filter": "Red",
   "frames": 260,
   "integration": 7800.0,
   "clouds": 0,
   "hfr": 2.419,
   "guide_rms": 0.436
  },
  {
   "filter": "Green",
   "frames": 259,
   "integration": 7770.0,
   "clouds": 0,
   "hfr": 2.419,
   "guide_rms": 0.448
  },
  {
   "filter": "Blue",
   "frames": 255,
   "integration": 7650.0,
   "clouds": 0,
   "hfr": 2.419,
   "guide_rms": 0.434
  }
 ],
 "failures": 0,
 "events": {
  "started": 1,
  "action": 504,
  "frame": 774,
  "trigger": 341,
  "condition": 1,
  "ending": 1,
  "ended": 1
 }
}
```
