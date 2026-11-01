# Soak: 

2026-11-01T06:52:01.550+00:00 → 2026-11-01T11:27:11.654+00:00 (4.59 h, 333 samples); slopes after the first 10 min.

## Processes

| process | n | RSS start → end (MB) | max | slope MB/h | fds start → end | max | CPU % mean / p95 |
|---|---|---|---|---|---|---|---|
| indi/indi_simulator_ccd | 1 | 76 → 73 | 128 | -0.2 | 5 → 5 | 6 | 4.1 / 8.3 |
| indi/indi_simulator_focus | 1 | 16 → 13 | 16 | -0.0 | 3 → 3 | 3 | 0.0 / 0.0 |
| indi/indi_simulator_guide | 1 | 26 → 23 | 26 | -0.0 | 4 → 4 | 5 | 3.4 / 3.7 |
| indi/indi_simulator_telescope | 1 | 17 → 14 | 17 | -0.0 | 3 → 3 | 3 | 0.1 / 0.1 |
| indi/indi_simulator_wheel | 1 | 16 → 13 | 16 | -0.0 | 3 → 3 | 3 | 0.0 / 0.0 |
| indi/indiserver | 1 | 8 → 8 | 10 | -0.0 | 22 → 22 | 23 | 0.9 / 1.0 |
| nocsd | 1 | 152 → 163 | 175 | 3.9 | 32 → 30 | 33 | 4.5 / 5.8 |
| nocsd/astap_cli | 1 | 213 → 213 | 213 | — | 6 → 6 | 6 | 3.3 / 3.3 |
| nocsd/resource_tracker | 1 | 21 → 16 | 21 | -0.4 | 4 → 4 | 4 | 0.0 / 0.0 |
| nocsd/worker | 1 | 160 → 160 | 349 | 5.9 | 11 → 11 | 13 | 10.7 / 13.4 |
| phd2/Xvfb | 1 | 24 → 23 | 24 | -0.1 | 9 → 9 | 9 | 0.4 / 0.5 |
| phd2/phd2.bin | 1 | 243 → 233 | 243 | -4.1 | 22 → 22 | 22 | 4.2 / 4.6 |

## The computer

- CPU temperature: 53.5 – 61.7 °C, mean 56.4
- throttled (cpufreq): False; under-voltage: False; vcgencmd get_throttled: 0x0
- load average (1 min): mean 0.52, max 1.33
- available memory: 6.56 GB at least
- storage free: 10.9 → 1.2 GB (frames pruned meanwhile: 372)
- nocsd wrote 19.8 GB (1.20 MB/s)
- the frames' drive took 24.1 GB of writes (1.46 MB/s)

## nocsd and the phone

- frames: 429 (93/h), 22.4 GB, 52.2 MB each
- `/api/health` latency (≈ event loop): p50 of windows 3.7 ms, worst p99 2517.1 ms, max 7512.1 ms; failures 0
- patch lag (clock posted → patch on the WebSocket): median 5.0 ms, max 641.6 ms; probes without a patch 1
- WebSocket: 31 connections (8 snapshots), 0 failures, 0 version gaps, 416045 patches (17.5 kB/s); slowest connection 35.9 ms
- downloads: 429 previews (slowest 120.9 ms), 43 FITS; 0 failures

## Log

- nothing at WARNING or above
- 1× `ERROR nocs.storage.service: no room to keep unsaved frame main_camera_NfcNffNdfNbNfNbNbN.fits; deleting it`

## The session report

```
{
 "filters": [
  {
   "filter": "Red",
   "frames": 145,
   "integration": 4350.0,
   "clouds": 0,
   "hfr": 2.419,
   "guide_rms": 0.447
  },
  {
   "filter": "Green",
   "frames": 145,
   "integration": 4350.0,
   "clouds": 0,
   "hfr": 2.42,
   "guide_rms": 0.448
  },
  {
   "filter": "Blue",
   "frames": 142,
   "integration": 4260.0,
   "clouds": 0,
   "hfr": 2.42,
   "guide_rms": 0.429
  }
 ],
 "failures": 1,
 "events": {
  "started": 1,
  "action": 286,
  "frame": 432,
  "trigger": 191,
  "failed": 1,
  "ending": 1,
  "ended": 1
 }
}
```
