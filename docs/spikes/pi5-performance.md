# Spike: performance on the Raspberry Pi 5

Date: 2026-10-30 · Status: **done on microSD** (USB SSD comparison pending) · Related:
[design §7 and §16](../design.md), [PHD2 spike](phd2-headless.md)

## Questions

1. Can the Pi 5 turn a 26 MP frame into a phone preview within ~2 s of download?
2. How long does ASTAP take to plate solve, hinted and blind?
3. What do indiserver and PHD2 cost in CPU and memory while guiding?
4. Does any of this make the Pi throttle (temperature / under-voltage)?
5. How much does the storage (microSD vs USB SSD) matter?

## The kit

[`dev/bench/run.sh`](../../dev/bench/run.sh) runs everything and writes a
results directory with `summary.md`:

| Step | Script | What it measures |
|---|---|---|
| samples | [make_samples.py](../../dev/bench/make_samples.py) | Configures the CCD simulator as the reference rig (6248×4176, 3.76 µm, 250 mm → 5.4°×3.6°), points the mount at SMC, M42 and M31, saves three 26 MP frames (one Bayer). Times exposure → received (INDI BLOB transfer). |
| preview | [preview_bench.py](../../dev/bench/preview_bench.py) | Load, debayer (superpixel / OpenCV), downscale to 1920 px (OpenCV / NumPy), auto stretch, WebP and JPEG encode; star detection and HFR with `sep`, full and 2×2 binned. |
| astap | [astap_bench.py](../../dev/bench/astap_bench.py) | ASTAP CLI solve per frame, hinted (position + FOV) and blind; time, success, scale. |
| guide | [phd2_probe.py](../../dev/spikes/phd2_probe.py) | Full PHD2 calibrate → guide → dither, while sampling `docker stats` every 5 s. |

## Running it on the Pi 5

1. **Prepare the card** with [`dev/pi/flash.sh`](../../dev/pi/README.md): Ubuntu
   Server 26.04 arm64 set up on first boot with Docker, uv, the repo and ASTAP
   (D50 database) in `/opt/astap`. Prefer an active cooler and the official 27 W
   supply.
2. **Run** over SSH, once per storage device to compare:

   ```sh
   ssh nocs-lab.local
   cd nocs
   # microSD (the OS disk)
   ASTAP=/opt/astap/astap_cli dev/bench/run.sh
   # USB SSD; containers are already built
   SKIP=build SAMPLES=/media/$USER/<ssd>/nocs-bench ASTAP=/opt/astap/astap_cli dev/bench/run.sh
   ```

   The first run builds the images on the Pi (several minutes; the INDI image
   downloads the ~240 MB GSC catalog).

3. **Share** the `summary.md` (and JSON files) from `dev/bench/results/<host>-<date>/`.
   Frames under `samples/` are not needed and are ignored by git.

What to look for: preview pipeline ≤ 2 s; hinted solve ≤ 5 s and blind ≤ 30 s;
PHD2 + indiserver well under 10 % CPU and 300 MB; `get_throttled=0x0` at the
end. Solved positions are compared with the mount's JNow coordinates while
ASTAP reports J2000, so an offset of up to ~25′ is expected; a correct scale
(~3.10″/px) confirms the solution.

## Baseline (x86_64, Intel Core Ultra 7 255H, NVMe)

Median of 3 runs, 26 MP frames:

| stage (ms) | mono | Bayer |
|---|---|---|
| load FITS | 36 | 36 |
| debayer superpixel / OpenCV | — | 57 / 26 |
| downscale OpenCV / NumPy | 22 / 108 | 22 / 157 |
| stretch | 64 | 213 |
| encode JPEG / WebP | 7 / 218 | 9 / 220 |
| **preview pipeline** (load + superpixel + OpenCV + stretch + JPEG) | **~130** | **~340** |
| stars full / binned 2×2 (sep) | 230 / 250 | 224 / 241 |

- Frame transfer: 5 s exposure received after 5.3 s (52 MB BLOB, local).
- Guiding (2 s exposures): PHD2 ~2 % CPU avg, 102 MiB; indiserver ~2 %, 75 MiB.
  Calibration ~70 s, settle 11–14 s.
- ASTAP: not measured on x86 (not installed here).

Early observations, to confirm on the Pi:

- **JPEG, not WebP**, for previews: WebP is ~30× slower to encode at similar
  size for these noisy images.
- **OpenCV** for downscaling and debayering: NumPy block-mean is 5× slower.
- The stretch on color frames is the slowest stage; computing statistics on a
  subsample instead of every pixel should cut it substantially.
- Star detection at full resolution costs ~0.25 s here; 2×2 binning did not
  save time with `sep`, so the binned path needs a different approach if the
  Pi is slow.

## Results on the Pi 5

Raspberry Pi 5 8 GB with active cooler, Ubuntu 26.04.1 (kernel 7.0 raspi),
frames on the **microSD**. Full data: [results/pi5-microsd](../../dev/bench/results/pi5-microsd/summary.md).

### Preview pipeline (median ms, 26 MP)

| stage | mono | Bayer | x86 baseline (mono / Bayer) |
|---|---|---|---|
| load FITS (microSD) | 137–162 | 141 | 36 / 36 |
| debayer superpixel / OpenCV | — | 232 / **141** | — / 57 / 26 |
| downscale OpenCV / NumPy | **66–86** / 154–160 | **68** / 355 | 22 / 108 |
| stretch | 105 | 338 | 64 / 213 |
| encode JPEG / WebP | **13** / 535 | **30** / 544 | 7 / 218 |
| **preview pipeline** | **320–370** | **~810** (≈720 with OpenCV debayer) | 130 / 340 |
| stars full / binned 2×2 | 790–880 / 500–550 | | 230 / 250 |

### ASTAP (D50 database)

| | hinted (position + FOV) | blind |
|---|---|---|
| `-z 1` (no downsampling) | **0.9–1.4 s**, 3/3 solved | **3.8–4.0 s**, 3/3 solved |
| `-z 0` (auto: 2×2 here) | 0/3 solved | 2/3 solved (one 180 s timeout) |

Offsets of 9–20′ are the expected JNow (mount) vs J2000 (solution) difference;
the solved scale (3.102″/px) matches the optics exactly.

### Guiding, transfer and thermals

- PHD2 + indiserver while calibrating, guiding and dithering: PHD2 2.9 % CPU
  average (9.4 % max), 126 MiB; indiserver 3.4 % (7.9 % max), 82 MiB. Load
  average ≤ 1.0 on 4 cores. Calibration and settling times equal to x86.
- 52 MB frame: received **1.0 s** after a 5 s exposure ends (0.3 s on x86).
- CPU 54–63 °C throughout, `throttled=0x0` before and after.

## Conclusions

1. **The Pi 5 is comfortably fast enough.** A full-size preview is ready in
   ~0.35 s (mono) / ~0.7 s (color) after download — well inside the 2 s target —
   with JPEG encoding and OpenCV for debayer and downscale. **Decision: JPEG
   previews, OpenCV in the imaging pipeline; no WebP** (40× slower to encode).
2. **Star metrics cost ~0.85 s** per full frame (0.5 s binned 2×2, which does
   help on the Pi). Fine for autofocus and per-frame quality, but they must run
   in a worker process, never on the event loop.
3. **Plate solving takes ~1.3 s hinted, ~4 s blind.** Solve-and-center and
   polar alignment will feel immediate. Downsampling must be chosen from the
   expected star size (HFR vs. pixel scale), not left on auto: ASTAP's auto
   binning failed on these sharp (undersampled) stars. To confirm on real frames.
4. **Guiding infrastructure is cheap** (~200 MB and < 10 % CPU together), leaving
   the Pi mostly idle during a session; the active cooler kept it far from
   throttling.
5. **BLOB transfer adds ~1 s per 26 MP frame** on the Pi. Irrelevant for
   long subs; worth profiling (base64 decode in the client) before short-exposure
   features like live view or focus loops.
6. **Packaging finding:** `sep` has no prebuilt arm64 wheel for Python 3.14,
   Ubuntu 26.04's system Python, and the image has no compiler. NOCS should run
   on its own managed Python (uv) pinned to a version with wheels for its
   scientific dependencies, rather than the system interpreter.
7. **Image-building findings for phase 6:** a first boot can easily happen
   without network (the lab setup now retries until online), and SourceForge
   throttles long downloads to tens of KB/s — the ASTAP database (~870 MB) must
   be baked into the image, never downloaded at first boot.

Still open: microSD vs USB SSD for frame storage (load time is the only stage
it affects: 140–160 ms per frame on microSD), and USB bandwidth with real
cameras attached.
