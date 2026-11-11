# Field notes: `v0.1.0rc2` on the rig, 2026-11-10

Working notes while the maintainer tests the rig outdoors from the `rc2` card
(`nocs.local`, `/api/health` says `0.1.0rc2`, INDI connected). Findings move to
[phase 6's findings](phase-6.md#612-findings-from-v010rc1) (or the phase they belong
to) once decided. `main` is already at `0.1.0rc3`: check each finding against it
before calling it open.

| Time | Where | Finding | Status |
|---|---|---|---|
| 22:12 | Guiding, connected to PHD2 | Alert "Camera ZWO CCD ASI220MM Mini, exposure error. Trying to use streaming instead.": PHD2's own message (in `phd2.bin`), relayed verbatim. PHD2's INDI camera saw the driver turn an exposure to Alert and falls back to the video stream. NOCS shows it with no cause and no next step. Cause unknown: to check whether NOCS still had the guide camera exposing when PHD2 took it, and in PHD2's debug log on the box | **Fixed** on its branch, `2d1201e` (NOCS leaves the guide camera idle before PHD2 connects, recognises the fallback and restarts PHD2 by a button or once by itself); going to `main`. Not tried on the rig |
| 22:20 | Plan → target → Framing | The survey image seems never to load: the caption stays at "Loading the survey image…". The phone fetches it itself from CDS hips2fits, then NASA SkyView (`SkyChart.svelte`, unchanged since `rc2`); by the code it turns "failed" after ≤ 42 s (12 s CDS + 30 s SkyView), sooner if offline, and every pan or zoom past the loaded image starts over. To know: does the phone have internet (box's access point or not), and how long it was left still. **Checked from the PC on the same home network (22:25):** `alasky.cds.unistra.fr` (130.79.128.175) does not even accept a TCP connection (timeouts at 15–25 s), as on 2026-11-01; SkyView returned M 23's 800×400 field in 9.9 s. So each chart waits 12 s for CDS, then ~10 s for SkyView: ~22 s with the chart and page still. The source that worked is remembered only inside one chart (`{#key object.id}` makes a new one per target), so every target starts with CDS again; any pan, zoom or resize in those 22 s starts over from CDS. Ideas: remember the working source across charts (module or prefs), try both at once or CDS with a much shorter timeout, say which service is being asked | Open: likely "too slow", not broken |
| 22:35 | Plan → NGC 2070 → Framing, on the PC | **To improve** (maintainer). The PC's browser, online, ends at "No survey image (offline?)": wrong words, the PC has internet. The view was 7.7° (≈ 10.4° × 7.7°): SkyView took **47 s** for that field from the PC (800×595, DSS2 Red), past its 30 s timeout, while CDS still refuses connections. SkyView's time grows with the field (9.9 s for 4° × 2°), so wide views never get an image. To do: say what failed (service not answering vs too slow vs offline); ask for a smaller field or fewer pixels when the view is wide, or skip the survey past some span; with the earlier row's ideas (remember the source, don't wait 12 s on CDS each time) | To act on |
| 22:40 | Plan → target, Go and centre while guiding | Refused with the bare "mount is busy (guiding)", and nothing to do from there. **The maintainer wants a button: "Go and resume guiding"** (stop guiding, go/centre, then guide again on the new field). Not fixed in `rc3`: #26 made park, home, the zenith and polar's "Go there" stop guiding first, not Plan's Go / Go and centre. The go to request already takes `stop_guiding` (ADR 0023); the centring request does not. Resuming needs a new guide star after the slew (PHD2 `guide` with star selection, settle), and the calibration still serves unless the camera turned or Dec changed a lot | **Fixed** in `main`: `e4a834a` (stop guiding, go or go and centre, guide again, as one job on the box). Not tried on the rig |
| 22:50 | Live view (preview), as a whole | **To rework** (maintainer). After a solve, the screen stacks the solution card (centre, angle, scale, offset from the mount), "Solved in 0.9 s · frame at …", "Mount synced" and the centring card with every frame's offsets: much information of little use at the rig. Missing instead, at a glance: **is the mount tracking?** (and similar live essentials). Once polar alignment is done it should not keep showing there. The dithering menu and a fixed frame count on the preview screen are not understood: what are they for there (they serve manual sub-frames, phases 2 and 4, but the screen does not say so). Besides the pad, the mount should be sent to a target **with autocentre** from here | To act on |
| 22:50 | Plan and Sequence | The maintainer finds it hard to tell what Plan and Sequence are for, apart: the split needs rethinking (or explaining in the app) | To act on |
| 22:50 | Box → Updates | **"Horrible", to rethink.** It shows "NOCS 0.1.0~rc2 · 176 updates (checked 10:48 AM)" and then every package with its version as one long run of text (alsa-ucm-conf, apt, at-spi2-core…). The OS packages drown NOCS's own update; the list says nothing useful for a decision | To act on |
| 23:10 | Plan → Go and centre | Centring takes its frames at **the camera's current exposure**, whatever Live view had (e.g. a long light), not a short one. Confirmed in the code: `CenterOptions.exposure`/`SolveOptions.exposure` default to "the camera's current exposure" (`pointing/solve.py` `_exposure` reads `cameras.<role>.exposure`), and the web app's `centerOn` sends none. **The maintainer wants a system setting for the centring (plate-solving) exposure, default 2 s.** Check also Live view's Solve, polar alignment and the sequence's centring (`sequence/rig.py`, which sets its own) against the same setting | **Fixed** in `main`: `36a0017`, the profile's `solving.exposure` (2 s by default, in the profile editor) for every solve. Kept in the profile, not box-wide: the maintainer to confirm |
| 11-11 01:00 | Session tab, on a large screen (PC, ~1900 px wide) | **To act on** (maintainer): large screens should use the space better. The page is one narrow centred column (~700 px) with wide empty margins; the frame is a small thumbnail, and the space under it is empty while the right column runs long (guiding, per filter, events). Seen in the same screenshot (B 33, a 20 × 120 s sequence), to check: the filter shows as "—" everywhere ("Exposing — · frame 5 of 20", "Frame - 120 s", thumbnails "- 1", Per filter "—"), a dash where the filter's name should be or where none is set; the event "Autofocus due: dither: 3 frames" reads oddly (a trigger's text joined to a dither's?) | To act on; the dashes and the event text to check |
| 11-11 01:08 | Session → Stop… | The dialog offers "After this frame, then park and warm", "Now, then park and warm" and "Now, and leave the rig as it is", but **not "After this frame, and leave the rig as it is"** (maintainer). The API already allows it: `SequenceStopRequest` takes `run_end` and `now` independently; only the dialog lacks the fourth combination | To act on (web only) |


## The night, from the box (read 2026-11-11 10:55 over the API)

Profile `am-2600` (AM5 driver, ASI2600MC Duo with its ASI220MM Mini guide sensor, EAF,
PPBA, no filter wheel), 382 mm, 2.03″/px; lights on the SanDisk USB drive. Local time
is UTC−3.

- **Session 2**, B 33, 00:50–01:09: 8 × 120 s, stopped by hand (the Stop dialog row
  above). Centred in 1 attempt (0.14′), autofocus 7085 → 7093 (HFR 2.34 → 1.90).
- **Session 3**, B 33, 01:10–05:05, **completed**: 104 × 120 s = **3.47 h of 3.91 h**
  (89 %), ended by "until dawn" at 05:00, then guiding off, park, warm. No clouds
  flagged.
  - HFR 1.53–1.74 (median 1.63), stars 1178–1768, sensor −10.0 ± 0.1 °C.
  - Guiding per frame: total RMS 0.59–1.03″ (median 0.74″; 5 frames over 1″, the
    first ones); RA median 0.57″, Dec 0.47″; 2 lost guide frames in the last 100.
  - Autofocus at the start (7093 → 7082) and twice on temperature (−1.2 °C, −1.1 °C:
    7070, 7054); focuser 17.6 → 15.4 °C, ambient 17 °C, humidity 85 %, dew point 14.7.
  - Dither every 3 frames (4.7 guide px, settled in 11–20 s); recentre every 10
    frames measured 0.8 → 1.8′ of drift before the flip, 0.3′ after, never past its
    2′ threshold.
  - **Meridian flip** at +3.4 min past the meridian (04:06): centred in 2 attempts
    (0.19′), pier east, guiding calibrated again; 4.6 min between frames.
  - One failure: at 02:11, right after a temperature autofocus, "PHD2 is not guiding
    (LostLock)"; retried, guiding back 30 s later, no frame lost. The report counts
    it as 1 failure and 0 recoveries.
- The box: CPU 53 °C, no under-voltage or throttling, 114 GB free inside, 239 GB on
  the USB drive; clock from NTP (−0.6 s).

Findings from the data:

| Where | Finding | Status |
|---|---|---|
| Sequence → gain | **All of the night's lights are at gain 0**: the sequence's rows say `gain: null`, "the camera's current gain", so they took what Live view had left (earlier nights: gain 100; after reconnecting this morning the camera says 100 again). Same kind of problem as the centring exposure: a sequence should not depend on what Live view last set. Gain 0 on the 2600 is its low-conversion-gain mode, more read noise | Gain 0 was meant. **Fixed** in `main`: `36a0017`, new sequence rows fix their gain and offset |
| Session report | The LostLock after autofocus was retried and guiding came back, but the report says 0 recoveries: a retry that worked is not counted as one | **Fixed** in `main`: `2153526` (a `recovered` event when a retry gets past a failure; the Session tab words each trigger by its own kind, the "Autofocus due: dither" text) |
| Calibration → Take darks and bias | For this night it built **330 frames** (~4 h): darks for every exposure among the lights, test frames included (2, 5, 10, 15, 30, 300 s with 1–3 lights each), and groups at 15 °C and 25 °C (lights taken warm, while cooling). Only the 112 × 120 s lights at −10 °C mattered. It should let you pick the groups, or leave out groups of a few lights | To act on |

Taken this morning by Claude, rig indoors with the cap on: the night's sequence
trimmed to **50 bias + 20 × 120 s darks at −10 °C, gain 0, offset 50**, then warm
(10:55–11:50, completed). The night's 112 × 120 s lights at −10 °C now match 20 darks
(−10.0 °C), 50 bias (−10.3 °C) and 20 flats; no flat darks ("flat_calibration": 0).

## Later (not for v0.1)

- **Integration with Stellarium**, and maybe other systems (maintainer, 22:55): to
  think about later. Candidates to weigh then: Stellarium's telescope control
  (choose an object there, NOCS goes and centres it), sharing the mount's position
  and the camera's frame with it, other planetaria and apps.

## Questions answered

## Afterwards
