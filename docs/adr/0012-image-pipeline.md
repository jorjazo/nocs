# 0012. Image transfer and preview pipeline

Date: 2026-10-30 · Status: Accepted

## Context

Every frame must reach disk intact and, within about two seconds, become a
preview on the phone with basic quality metrics (star count, HFR). Facts measured
on the lab Pi 5 ([spike](../spikes/pi5-performance.md)):

- A 26 MP frame received as an INDI BLOB (base64 inside XML) is ready 1.5 s after
  the exposure ends and **blocks nocsd's event loop for ~0.3 s** while it is
  decoded. A separate connection for images keeps other devices' state from
  queuing behind it on the wire, but the CPU cost stays in the process.
- With `UPLOAD_MODE = UPLOAD_LOCAL` the driver writes the FITS itself and sends
  only its path: ready 0.7 s after the exposure, the event loop untouched. It
  requires indiserver and nocsd to share a filesystem, which is always the case on
  the Pi.
- Preview (load, debayer, downscale, stretch, JPEG) takes 0.35 s mono / 0.7 s
  color on the Pi; star detection with `sep` 0.5 s on a 2×2-binned frame. JPEG
  encodes 40× faster than WebP; OpenCV debayers and downscales 2–5× faster than
  NumPy. All of it is CPU-bound work that must not run on the event loop.
- OpenCV names Bayer patterns differently from FITS: an `RGGB` sensor needs
  `COLOR_BayerBG2RGB`.

## Decision

- **Transfer.** When nocsd is told where indiserver can write
  (`NOCS_INDI_UPLOAD_DIR`, plus the same directory as nocsd sees it when they
  differ, as with the dev container), cameras use `UPLOAD_LOCAL` into that
  directory and nocsd moves each file to its destination. Otherwise images arrive
  as BLOBs on a connection of their own, accepting the event-loop cost (a remote
  indiserver is not the appliance case).
- **Processing in one worker process** (a `ProcessPoolExecutor` with a single
  `spawn`ed worker): it receives the path of a FITS file and returns a small
  result (preview path, size, metrics, histogram). Pixels never cross the
  process boundary or touch the event loop. One worker keeps memory bounded on
  the Pi (a 26 MP color frame is ~0.6 GB as float32 RGB) and is enough at the
  measured speed.
- **Pipeline:** read FITS (astropy) and its Bayer pattern and row order →
  debayer (OpenCV, pattern translated) → downscale to at most 1920 px wide
  (`INTER_AREA`) → automatic midtones-transfer stretch per channel with
  statistics from a subsample → JPEG quality 85 (OpenCV). Stars with `sep` on the
  luminance, 2×2 binned when the frame is larger than 4 MP: count and median HFR
  in unbinned pixels. A 256-bin histogram of the linear data.
- **Previews are transient:** the last few per camera live under
  `<data dir>/previews/`, served over HTTP with immutable URLs and announced in
  the camera's state (ADR 0005: binary data out of the state channel). Night
  mode tints them in the client.
- **Loop mode** (framing, focusing) exposes repeatedly without keeping the FITS.
  The pipeline never queues: if a frame arrives while the previous one is still
  being processed, it replaces any frame waiting, so the preview is always the
  newest one.

## Consequences

- The appliance gets frames in half the time with no stalls; the dev container
  and CI exercise the same path through a shared directory.
- A crash in OpenCV or `sep` kills the worker, not nocsd; the pool is recreated.
- Scientific dependencies (numpy, OpenCV, sep, astropy) become part of nocsd,
  pinning it to a Python with arm64 wheels for them (3.12/3.13, see the Pi spike).
- Autofocus (phase 5) reuses the same worker for HFR, without previews.
- `UPLOAD_MODE` belongs to the device and is shared by every INDI client: a camera
  in `UPLOAD_LOCAL` sends no BLOBs to anyone. PHD2 receives the guide camera's
  frames as BLOBs, so before guiding (phase 4) the guide camera must stay in
  `UPLOAD_CLIENT` (its frames are small; preferred) or use `UPLOAD_BOTH`. The same
  applies to any other client sharing a camera, such as KStars.
- Measured on the Pi with a 26 MP color camera: preview published ~2.1 s after
  the exposure ends (0.7 s driver, 1.4 s worker), with the event loop free.
