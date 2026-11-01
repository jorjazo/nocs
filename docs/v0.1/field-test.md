# Field test: one clear night, phases 2 to 5

One run order for the whole rig (AM5, ASI2600MC Duo with its ASI220MM guide sensor,
EFW, EAF, PPBA on the lab Pi 5), covering what exists on `main` now. Steps marked
**Exit** are a phase's exit criterion:

| Phase | Exit criterion | Steps |
|---|---|---|
| [2](phase-2.md) | Manual sub-frames controlled only from a phone | 1–9, 11–13, 21 |
| [3](phase-3.md) | Pick NGC 292 on the phone, go there and centre it; then NGC 253 | 10 |
| [4](phase-4.md), polar half | Polar align from the phone within 1′ | 5 |
| [4](phase-4.md), guiding half | Guided 300 s sub-frames with dithering, total RMS under 1″, round stars | 14–18 |
| [5](phase-5.md) | A multi-filter sequence from dusk to a parked dawn, with a meridian flip | 19–20, in part: see there |

The rule of every exit: **no laptop and no SSH** during the night. If one is needed,
note why: that is a finding, and that phase's test is not passed. Note also
everything that needed a second try or a workaround, and the battery of the Pi and
the phone over the night.

## Before going out

- [ ] `main` has the stages listed above and CI is green.
- [ ] The Pi runs that commit (lab lock, `~/nocs-app`): fast-forward, `uv sync`, a
      `web/dist` built from the same commit, nocsd restarted. `indiserver@` runs with
      no extra drivers and `phd2@$USER` is active; nocsd runs with
      `NOCS_PHD2_SETTINGS=$HOME/.local/share/nocs/phd2.phd`, the file the unit imports
      (dev/pi/README.md).
- [ ] A network for the phone and the Pi at the site: the phone's hotspot or a
      travel router. The phone reaches `http://<pi>.local:8000` or the Pi's IP, and
      is paired as owner (ADR 0014).
- [ ] The profile, in the profile editor:
  - every role (main and guide camera, mount, focuser, filter wheel, power box),
    serial ports by `/dev/serial/by-id/`;
  - both trains' optics; "The guide camera looks through the imaging optics" on
    for the Duo;
  - the site (name, latitude, longitude, elevation) and the filter names;
  - autofocus: overshoot ~1000 for the EAF on the 380 mm scope (its backlash is
    600–700 steps, phase 5's field notes).
- [ ] Storage: a USB drive mounted by fstab, or internal, with room for the night.
- [ ] Indoors, with the lab lock: connect the profile; Guiding says "Runs the
      profile's settings"; Connect, Loop, Stop looping, Disconnect.

## At the site, all from the phone

**Set up (phase 2)**

1. **Power and connect.** PPBA on; connect the profile on Rig, every role ready.
   Switch on the outputs the rig needs and the dew heaters.
2. **Time and site.** The mount gets the site, then the phone's time; the clock
   warning is gone, or frame times are corrected (ADR 0015).
3. **Cooling.** The camera's target (e.g. −10 °C) with a ramp; watch power and
   temperature meanwhile.
4. **Mount.** Unpark. Nudge it with the slew pad: the speeds read 0.25x…1440x, and
   the chosen one is the one it moves at. The dead man's switch stops it when the
   finger lifts or the Wi-Fi drops.

**Polar alignment (phase 4)**

5. **Exit, phase 4 polar.** Polar alignment (`#/polar`, from Tonight, Live view or the mount sheet): three solved
   points, then the error with "Raise / Turn" readouts; adjust until within 1′.
   Note the time it took and the error after a second check.

**Framing and focus (phase 2, phase 5)**

6. **Framing.** Loop on the main camera, binned, short exposures. Open the pad in
   Live view: the preview stays on top with its centre marked, and a star moves
   across it while an arrow is held. Zoom; check stars and HFR.
7. **Focus by hand.** EAF in or out while looping until HFR reaches a minimum.
   Note the position and the focuser's temperature.
8. **Autofocus.** Step 100–300, 9 points, 2–3 s: the ends of the sweep clearly out
   of focus; take the step it suggests and run again (phase 5's tuning list, steps
   2–6, if the night allows).
9. **Filter.** Change it from Live view; preview and frame folder follow.

**Go and centre (phase 3)**

10. **Exit, phase 3.** Plan → NGC 292 → Go and centre: it lands within 1′, the
    centring card listing each frame; then NGC 253 the same way. Choosing the
    target also names the lights' folder (`Light/NGC_253/`).

**Manual sub-frames (phase 2)**

11. **Guide camera.** Switch Live view to the guide camera; a 1–2 s loop shows stars.
    Nothing is saved. Switch back.
12. **Exit, phase 2: sub-frames.** The target row in Live view names the folder.
    Light frames, gain and offset, exposure; Save on; 10 × 60–180 s with the shutter,
    the phone locked between frames. The caption names where the last one went.
13. **Exit, phase 2: check the frames.** Session tab: the night's frames with stars
    and HFR. Download one frame, then the night's zip (its size shows first).

**Guiding (phase 4)**

14. **PHD2.** Live view → Guiding: PHD2's version and "Runs the profile's settings".
    Connect: camera and mount connected; Live view shows the guide camera as PHD2's.
    Exposure 2 s (3–4 s through narrowband: the Duo's guide sensor is behind the
    filters).
15. **Calibrate and guide.** Start guiding with "Calibrate again" on (first night,
    or after rotating the camera). Note the time it takes, the declination and the
    rates, and any alert.
16. **Watch.** Five minutes of the graph: RMS in RA, Dec and total, SNR and HFD, lost
    frames; ″ and px. Dither now, 5 px: the dotted line and the settling time.
    The mount sheet says PHD2 guides and offers "Stop guiding"; the pad is off.
17. **Exit, phase 4 guiding.** Main camera, lights, 300 s, Save on, 10 frames,
    dither every frame, phone locked. The status shows the frame and "Dithering"
    between them; total RMS under 1″. The Session tab shows each frame's RMS.
18. **Stop.** Stop guiding, then Disconnect: Live view gives the guide camera back.

**Sequence (phase 5)**

19. **A short sequence.** Plan → Sequence on the night's target: two filters,
    3 × 120 s each, autofocus at the start, guiding on, park and warm when finished.
    Start it with guiding stopped (starting while PHD2 guides is refused for now,
    phase 5's QA notes). Watch it in the Session tab: frame i of N per filter, the
    events, the guiding graph; Pause, then Resume. Lock the phone.
20. **Exit, phase 5, in part.** If the night allows, a longer run on a target that
    stays on one side of the meridian, until dawn or a set time, ending parked.
    The meridian flip (5.18), dithering (5.16) and re-centring (5.17) inside a
    sequence are not built yet: the full exit waits for them.

**End (phase 2)**

21. Cooler off with the ramp, park, outputs off, disconnect the profile.

If the sky allows, also try: a cloud or a lost guide star (an alert, lost frames in
the graph, whether guiding picks up again by itself, what a running sequence does);
a 120 s series dithering every 3 frames; autofocus through a cloud or with the cap on
(it fails with its reason and goes back where it started).

## Afterwards, at home

- [ ] FITS headers of a light frame: `OBJECT`, `OBJCTRA`/`OBJCTDEC` against the
      target, `FILTER`, `FOCUSPOS`, `CCD-TEMP` and `SET-TEMP`, `GAIN`/`OFFSET`,
      `SITENAME`/`SITELAT`/`SITELONG`/`SITEELEV`, `FOCALLEN`/`APTDIA`, and `DATE-OBS`
      against the phone's time.
- [ ] The frames open and stack in Siril or PixInsight (Bayer pattern, row order,
      round stars); registration shows the dithers as shifts of a few pixels.
- [ ] Each frame's guiding RMS, steps and lost frames (Session tab, `GET /api/frames`)
      against PHD2's guide log on the Pi (`~/PHD2/PHD2_GuideLog_*.txt`).
- [ ] The session report (5.15) and its events against what happened; the autofocus runs' positions
      and R².
- [ ] Notes, with every finding as an issue or a next stage; mark the exits that
      passed in each phase's plan with a line on the result.
