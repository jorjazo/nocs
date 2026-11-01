# Phase 4 field test: polar alignment and guiding

The exit criterion of [phase 4](phase-4.md): from a phone, polar align the mount within
1′, then calibrate and guide, and take guided 300 s sub-frames with a dither between
them, with a total guiding RMS under 1″ and round stars. Like
[phase 2's](field-test.md), no laptop and no SSH during the session: if one is needed,
note why, and the test is not passed.

## Before going out

- [ ] `main` has stages 4.1 to 4.10, CI is green, and the phase 2 field test's list is
      done (the rig, the network, the phone paired).
- [ ] The Pi runs that commit: server (`uv sync`) and `web/dist` updated together.
      `phd2@$USER` is active (`systemctl is-active phd2@$USER`), and nocsd runs with
      `NOCS_PHD2_SETTINGS=$HOME/.local/share/nocs/phd2.phd`, the file the unit imports
      (dev/pi/README.md). Without it NOCS uses PHD2 as it is set up.
- [ ] The profile, in the profile editor:
  - the guide camera role (the Duo's `ZWO CCD ASI220MM Mini`) and the mount;
  - "The guide camera looks through the imaging optics" on for the Duo or an OAG;
    otherwise the guide scope's optics in the guiding train;
  - the imaging train's focal length and reducer: dithers are given in main camera
    pixels and converted with both trains.
- [ ] A lab check at home, indoors, holding the lab lock: connect the profile; the
      guiding screen says "Runs the profile's settings"; Connect; Live view shows the
      guide camera as PHD2's, with its frames; Loop, then Stop looping; Disconnect.
      Calibrating needs stars, so it waits for the field.
- [ ] The lab check of polar alignment's RA turns on the mount (stage 4.11) passed:
      the pier side and Dec held through two 30° turns, with and without a sync.
- [ ] The tripod or pier roughly levelled and the mount roughly at the site's
      latitude: the knobs have a few degrees of travel at most.

## At the site, all from the phone

1. **The rig.** Steps 1 to 6 of the phase 2 checklist: power, time and site,
   cooling, the mount on the target, framing and focus. Polar alignment solves
   frames: focus first, roughly is enough.
2. **Polar alignment.** Tonight → Polar align (also in Live view and the mount sheet).
   - "Where to start" → Go there: Dec −60° at the lab's site, half an hour east of the
     meridian. Stars must be in view there; if not, start elsewhere on the pole's side
     of the zenith and away from the meridian (the job says why it refuses a start).
   - Exposure enough for a few dozen stars (2–5 s), the camera's binning, 30° turns.
     Start. The three points fill in: the mount turns 30° east twice, never crosses
     the meridian (watch the pier: no flip). Note "The RA axis turned …" (should read
     30°, 30°) and any warning.
   - The target and the two instructions ("Raise the polar axis …", "Turn the axis …
     east/west"). Turn one knob a little; the next frame says how far it moved and
     which way. **Check the words against the knobs**: "Raise" must raise the axis,
     "east" must turn it east. Note the AM5's knob directions for next time.
   - Reach "Aligned" (under 1′). Note how long it took and how many frames; then
     Finish: the mount goes back to the start.
   - Run it again without touching the knobs: the new error should be within ~1′ of
     where the first run ended. That is the method's repeatability.
3. **PHD2.** Live view → Guiding. The screen shows PHD2's version and "Runs the
   profile's settings". Connect: camera and mount connected to PHD2. Back in Live
   view, the guide camera shows PHD2's frames with stars; the main camera is free.
4. **Exposure.** 2 s; 3–4 s through a narrowband filter with the Duo, whose guide
   sensor sits behind the filters.
5. **Calibrate and guide.** Start guiding with "Calibrate again" on (the first night,
   or after rotating the camera). Note how long calibration takes, the declination
   and rates it shows, and any alert. The job ends once PHD2 has settled.
6. **Watch.** Five minutes of the graph: RMS in RA, Dec and total (″), SNR and HFD,
   frames without the star. Switch between ″ and px.
7. **Dither now**, 5 px: the dotted line in the graph, and how long settling takes.
8. **The mount waits.** Open the mount sheet: it says PHD2 is guiding and offers
   "Stop guiding"; the pad is off. Do not stop it now.
9. **Guided sub-frames.** Main camera, light frames, 300 s, Save on, 10 frames,
   "Dither every frame". Lock the phone. The status shows the frame of the series
   and the dithers between them; the guiding link shows the RMS.
10. **Stop.** On the guiding screen, Stop guiding, then Disconnect: Live view gives
   the guide camera back.
11. **End.** The phase 2 checklist's last step: cooler off, park, outputs off,
    disconnect the profile.

If the sky allows, also try:

- A cloud or a lost star: an alert, frames without the star in the graph, and
  whether guiding picks up again by itself.
- A series of 120 s frames dithering every 3 frames.

## Afterwards, at home

- [ ] Each frame's guiding RMS, steps and lost frames in the catalog
      (`GET /api/frames`; the frame list does not show them yet) against PHD2's own
      guide log on the Pi (`~/PHD2/PHD2_GuideLog_*.txt`).
- [ ] The frames stack in Siril or PixInsight with round stars; registration shows
      the dithers as shifts of a few pixels between frames.
- [ ] Notes: everything that needed a second try, a laptop or a workaround; the
      calibration and settling times; battery use. These become issues or the next
      stages.
- [ ] Guiding's Dec corrections as a check of the polar alignment: with the error
      under 1′, PHD2's Dec should need few and small corrections (its guide log).
- [ ] Mark 4.7 and 4.11 done in [phase-4.md](phase-4.md) with a line on the result:
      the polar error found, the time to align, the repeatability.
