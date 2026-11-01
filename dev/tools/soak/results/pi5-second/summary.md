# Soak: pi5-20261101-0830

2026-11-01T11:31:39.559+00:00 → 2026-11-01T12:57:21.822+00:00 (1.44 h, 172 samples); slopes after the first 10 min.

## Processes

| process | n | RSS start → end (MB) | max | slope MB/h | fds start → end | max | CPU % mean / p95 |
|---|---|---|---|---|---|---|---|
| indi/indi_simulator_ccd | 1 | 77 → 77 | 129 | 0.3 | 5 → 5 | 7 | 4.2 / 8.8 |
| indi/indi_simulator_focus | 1 | 15 → 15 | 15 | 0.0 | 3 → 3 | 3 | 0.0 / 0.0 |
| indi/indi_simulator_guide | 1 | 25 → 25 | 25 | 0.0 | 4 → 4 | 4 | 3.2 / 3.5 |
| indi/indi_simulator_telescope | 1 | 16 → 16 | 16 | 0.0 | 3 → 3 | 3 | 0.1 / 0.1 |
| indi/indi_simulator_wheel | 1 | 15 → 15 | 15 | 0.0 | 3 → 3 | 3 | 0.0 / 0.0 |
| indi/indiserver | 1 | 9 → 9 | 9 | 0.0 | 22 → 22 | 22 | 0.9 / 1.0 |
| nocsd | 1 | 160 → 166 | 172 | 2.6 | 33 → 31 | 35 | 5.5 / 5.9 |
| nocsd/astap_cli | 1 | 213 → 107 | 213 | — | 7 → 8 | 8 | 2.3 / 3.4 |
| nocsd/cat | 1 | 6 → 6 | 6 | 0.0 | 5 → 5 | 5 | 0.0 / 0.0 |
| nocsd/resource_tracker | 1 | 21 → 21 | 21 | 0.0 | 4 → 4 | 4 | 0.0 / 0.0 |
| nocsd/worker | 1 | 122 → 198 | 340 | 22.2 | 11 → 11 | 12 | 10.0 / 13.1 |
| phd2/Xvfb | 1 | 24 → 24 | 24 | 0.0 | 9 → 9 | 9 | 0.4 / 0.5 |
| phd2/phd2.bin | 1 | 238 → 238 | 238 | 0.0 | 22 → 22 | 22 | 4.1 / 4.6 |

## The computer

- CPU temperature: 54.0 – 61.7 °C, mean 56.9
- throttled (cpufreq): False; under-voltage: False; vcgencmd get_throttled: 0x0
- load average (1 min): mean 0.94, max 5.09
- available memory: 5.98 GB at least
- storage free: 13.5 → 9.5 GB (frames pruned meanwhile: 63)
- nocsd wrote 5.8 GB (1.12 MB/s)
- the frames' drive took 9.1 GB of writes (1.76 MB/s)

## nocsd and the phone

- frames: 123 (86/h), 6.4 GB, 52.2 MB each
- `/api/health` latency (≈ event loop): p50 of windows 3.7 ms, worst p99 4097.2 ms, max 4097.2 ms; failures 0
- patch lag (clock posted → patch on the WebSocket): median 5.0 ms, max 120.2 ms; probes without a patch 1
- WebSocket: 10 connections (3 snapshots), 0 failures, 0 version gaps, 130422 patches (17.6 kB/s); slowest connection 25.7 ms
- downloads: 123 previews (slowest 166.3 ms), 12 FITS; 0 failures

## Log

- nothing at WARNING or above

## The session report

```
{
 "filters": [
  {
   "filter": "Red",
   "frames": 43,
   "integration": 1290.0,
   "clouds": 0,
   "hfr": 2.44,
   "guide_rms": 0.43
  },
  {
   "filter": "Green",
   "frames": 40,
   "integration": 1200.0,
   "clouds": 0,
   "hfr": 2.44,
   "guide_rms": 0.4505
  },
  {
   "filter": "Blue",
   "frames": 40,
   "integration": 1200.0,
   "clouds": 0,
   "hfr": 2.439,
   "guide_rms": 0.435
  }
 ],
 "failures": 0,
 "events": {
  "started": 1,
  "action": 86,
  "frame": 123,
  "trigger": 53,
  "ending": 1,
  "ended": 1
 }
}
```
