# Benchmark results: pi5-microsd

```
date: 2026-10-30T03:41:56-03:00
Linux nocs-lab 7.0.0-1020-raspi #20-Ubuntu SMP PREEMPT_DYNAMIC Fri Sep 11 16:02:28 UTC 2026 aarch64 GNU/Linux
PRETTY_NAME="Ubuntu 26.04.1 LTS"
VERSION_ID="26.04"
Model		: Raspberry Pi 5 Model B Rev 1.0
cpus: 4
               total        used        free      shared  buff/cache   available
Mem:            7931        1646         396         880        6960        6285
Swap:              0           0           0
samples storage:
Filesystem      Size  Used Avail Use% Mounted on
/dev/mmcblk0p2   29G  7.9G   20G  29% /
SOURCE         FSTYPE TARGET
/dev/mmcblk0p2 ext4   /
thermals (start): temp=56.0'C throttled=0x0
Docker version 29.1.3, build 29.1.3-0ubuntu4.1
uv 0.13.6 (aarch64-unknown-linux-gnu)
thermals (end): temp=56.0'C throttled=0x0
```

## Frame transfer (INDI simulator, 26 MP)

| frame | exposure | expose→received |
|---|---|---|
| smc.fits | 5.0 s | 6.01 s |
| m42.fits | 5.0 s | 6.04 s |
| m31_bayer.fits | 5.0 s | 5.98 s |

## Preview pipeline (aarch64, OpenCV threads 4)

| stage (median ms) | smc.fits | m42.fits | m31_bayer.fits |
|---|---|---|---|
| load | 162 | 137 | 141 |
| downscale_opencv | 86 | 66 | 68 |
| downscale_numpy | 154 | 160 | 355 |
| stretch | 105 | 106 | 338 |
| encode_webp | 539 | 532 | 544 |
| encode_jpeg | 13 | 13 | 30 |
| stars_full | 856 | 884 | 788 |
| stars_bin2 | 547 | 539 | 502 |
| pipeline_preview | 367 | 321 | 809 |
| debayer_superpixel | — | — | 232 |
| debayer_opencv | — | — | 141 |
| stars (full / bin2) | 404 / 389 | 426 / 422 | 670 / 670 |

## ASTAP

| frame | mode | solved | time | error |
|---|---|---|---|---|
| smc.fits | hinted z1 | True | 1.36 s | 9.09′ |
| smc.fits | blind z1 | True | 3.81 s | 9.09′ |
| m42.fits | hinted z1 | True | 1.34 s | 20.11′ |
| m42.fits | blind z1 | True | 3.96 s | 20.12′ |
| m31_bayer.fits | hinted z1 | True | 0.88 s | 19.22′ |
| m31_bayer.fits | blind z1 | True | 3.82 s | 19.22′ |

## Resources while guiding

| container | CPU avg | CPU max | memory max |
|---|---|---|---|
| dev-indi-1 | 3.3 % | 7.9 % | 82 MiB |
| dev-phd2-1 | 3.6 % | 16.9 % | 126 MiB |

Load average: max 1.04
CPU temperature: 54.5 to 63.4 °C

```
guiding settled after 86 s: {'Event': 'SettleDone', 'Timestamp': 1793342831.491, 'Host': '47e74da273fc', 'Inst': 1, 'Status': 0, 'TotalFrames': 5, 'DroppedFrames': 0}
dither settled: {'Event': 'SettleDone', 'Timestamp': 1793342865.536, 'Host': '47e74da273fc', 'Inst': 1, 'Status': 0, 'TotalFrames': 6, 'DroppedFrames': 0}
```
