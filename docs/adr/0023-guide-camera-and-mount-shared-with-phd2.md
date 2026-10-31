# 0023. Guide camera and mount shared with PHD2

Date: 2026-10-31 · Status: Proposed

## Context

PHD2 drives the guide camera and the mount through INDI itself (ADR 0022), while
NOCS uses the same devices: Live view exposes with the guide camera (stage 2.11),
and the mount moves by the pad, go to, park and home (ADR 0015). INDI lets every
client command every device, so who may do what has to be decided by NOCS.
Facts from stages 4.1 and 2.11:

- A camera has one exposure at a time. A NOCS exposure while PHD2 loops would
  change the exposure time PHD2 set and hand PHD2 a frame it did not ask for.
- Connecting PHD2's equipment resets the guide camera's `CCD_FRAME` to the full
  sensor; disconnecting it (`set_connected false`) leaves the devices connected,
  on the simulators and on the ZWO drivers.
- PHD2 refuses to disconnect while an exposure is in progress: `stop_capture`
  answers at once, the capture ends with `LoopingExposuresStopped` or
  `GuidingStopped`.
- The upload mode belongs to the device: the guide camera stays in
  `UPLOAD_CLIENT` so PHD2 gets its frames as BLOBs (ADR 0012). NOCS's own image
  connection for that camera receives every frame PHD2 takes too: ~4 MB every
  1–2 s for the ASI220MM Mini, cheap to decode.
- Pulse guiding (`TELESCOPE_TIMED_GUIDE_*`) does not conflict with NOCS's
  reading of the mount, but a slew, a park or the pad move the guide star out of
  reach.

## Decision

- **PHD2 owns the guide camera while its equipment is connected**, not only
  while it guides: NOCS holds the `guide_camera` role with a reservation
  (`JobManager.reserve`) named `guiding`. NOCS's exposures, loops and settings
  changes on that camera are refused meanwhile; cooling is not, since PHD2 does
  not cool. Connecting is refused while a NOCS job holds the camera.
- **Connecting needs PHD2 to run NOCS's settings** for the active profile
  (ADR 0022), and NOCS applies new settings only while PHD2's equipment is
  disconnected.
- **Disconnecting stops PHD2's capture first**, waits for it to end, then
  disconnects PHD2 and frees the camera. Disconnecting the equipment profile
  does the same first; losing PHD2 (it exits or restarts) frees the camera.
- **Live view shows what PHD2 sees**: while PHD2 holds the camera, each frame it
  takes arrives on NOCS's image connection and goes through the usual preview
  pipeline (newest frame wins, ADR 0012). The camera's state says it is used by
  PHD2, so the app hides the shutter and settings.
- **The mount is held while PHD2 calibrates or guides** (and while a start of
  guiding runs), with a second `guiding` reservation; pulse guiding itself
  needs no lock. Go to, park, home, the pad, tracking and site changes are
  refused meanwhile. Go to, park and home take `stop_guiding`, which stops PHD2
  first (the app asks for a second tap); abort stops the mount regardless.

## Consequences

- One rule covers looping, calibrating and guiding: the camera is PHD2's from
  "connect" to "disconnect", and the app shows its frames rather than nothing.
- A user who wants the guide camera back in Live view disconnects guiding;
  phase 5's sequencer connects PHD2 at the start of a session and releases it at
  the end.
- Decoding PHD2's frames costs nocsd some event-loop time per frame (a BLOB):
  on the lab Pi, with the ASI220MM Mini looping 1 s exposures, nocsd still
  answered `GET /api/state` in 12 ms (median; 58 ms at most).
