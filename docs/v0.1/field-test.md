# Field test: one clear night, phases 2 to 5

One run order for the whole rig (AM5, ASI2600MC Duo with its ASI220MM guide sensor,
EFW, EAF, PPBA on the lab Pi 5), covering what exists on `main` now. Steps marked
**Exit** are a phase's exit criterion:

| Phase | Exit criterion | Steps |
|---|---|---|
| [2](phase-2.md) | Manual sub-frames controlled only from a phone | 1–9, 11–13, 21 |
| [3](phase-3.md) | Pick NGC 292 on the phone, go there and centre it; then NGC 253, framed | 10, 13 |
| [4](phase-4.md), polar half | Polar align from the phone within 1′ | 5 |
| [4](phase-4.md), guiding half | Guided 300 s sub-frames with dithering, total RMS under 1″, round stars | 14–18 |
| [5](phase-5.md) | A multi-filter sequence from dusk to a parked dawn, with a meridian flip | 19–20, in part: see there |
| [Calibration](../beyond/calibration.md) | Sky flats at twilight and the night's darks and bias, matched to its lights | 22–23 |

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
- [ ] Solver: ASTAP and D50 in `/opt/astap` (Live view's Solve is enabled; D05 does
      not solve dense Milky Way fields, ADR 0018).
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

5. **Exit, phase 4 polar.** Polar alignment (`#/polar`, from Tonight, Live view or
   the mount sheet). It solves frames: if the stars are soft, focus roughly first
   (step 7). "Go there" takes the mount to the suggested start (Dec −60°, half an
   hour east of the meridian); 2–5 s, 30° turns. The three points fill in while the
   mount turns east twice without a flip; "The RA axis turned" should read 30°, 30°.
   Turn one knob a little and **check the words against the knobs**: "Raise" must
   raise the axis and "east" turn it east (note the AM5's directions). Adjust until
   "Aligned" (under 1′), Finish (back to the start), then run it again without
   touching the knobs: note the time it took and the second run's error.

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

10. **Exit, phase 3.** Plan → search "SMC" → NGC 292's page: the altitude chart
    over the site's horizon, the framing chart with the main camera's frame. Go and
    centre: it lands within 1′, the centring card listing each frame. Then NGC 253
    the same way, framed:
    - drag the chart to place the galaxy in the frame and set the camera rotation;
      Go and centre goes where the frame points;
    - "Turn the camera N°" says how far to turn it by hand; turn it, Solve in Live
      view: the dashed solved frame on the chart is within ~2° of the framing;
    - choosing the target also names the lights' folder (`Light/NGC_253/`) and
      Tonight shows it as tonight's target;
    - with the survey image on (if the phone has internet), NGC 253 lies under its
      outline.

    Note whether nocsd logged that the mount "went back" after a sync, and whether
    the next go to still landed (phase 3's decisions: the AM5 near its home).

**Manual sub-frames (phase 2)**

11. **Guide camera.** Switch Live view to the guide camera; a 1–2 s loop shows stars.
    Nothing is saved. Switch back.
12. **Exit, phase 2: sub-frames.** The target row in Live view names the folder.
    Light frames, gain and offset, exposure; Save on; 10 × 60–180 s with the shutter,
    the phone locked between frames. The caption names where the last one went.
13. **Exit, phase 2: check the frames.** Session tab: the night's frames with stars
    and HFR. Download one frame, then the night's zip (its size shows first).
    **Phase 3, own frames:** Plan → NGC 253: "Solve one" solves the light with the
    most stars; it then lies under the chart's stars ("My frames"), turned as the
    camera was. Live view's "Solve this frame" on a saved light does the same.

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
    Start it with guiding running by hand: the sequence takes it over. Watch it in the Session tab: frame i of N per filter, the
    events, the guiding graph; Pause, then Resume. Lock the phone.
20. **Exit, phase 5, in part.** If the night allows, a longer run on a target that
    stays on one side of the meridian, until dawn or a set time, ending parked.
    For the full exit, a target that crosses the meridian: on the AM5 keep its own
    flip off (`MERIDIAN_FLIP` disabled, post-meridian tracking on, as in the lab) or
    its limit past NOCS's flip point (5 min by default); centring on, guiding with
    dither every 3 frames. NOCS flips before the frame that would end past that
    point (the lab AM5 took 33 s), centres, calibrates guiding again and carries on.

**End (phase 2)**

21. Cooler off with the ramp, park, outputs off, disconnect the profile (after
    step 23 if it runs tonight).

**Calibration (ADR 0036)**

22. **Sky flats.** At dusk before the first target, or at dawn before parking:
    Session tab → the night's Calibration → Take flats → Twilight sky. The windows
    (Sun between −1° and −10°) match the clock; started early, it waits for the
    window. The mount goes high opposite the Sun with tracking off; narrowband
    filters first at dusk, last at dawn. Note each filter's exposures as the sky
    darkens (or brightens), how many flats it kept against the count, and whether a
    filter "ended" because the twilight left the limits. The filter, the focuser
    at the lights' position and the rotation must not change after the lights.
23. **Darks and bias.** At the end, the cap on the scope: Calibration → Take darks
    and bias, leave it running (warm at the end on). It cools to each group's
    temperature, takes the bias and the darks, and the Calibration card turns
    complete; the phone can sleep meanwhile.

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
- [ ] Calibration: the night's zip with "calibration" holds the darks, flats and bias
      the card shows; their `IMAGETYP` (Dark, Flat, Bias), `CCD-TEMP`, `GAIN`/`OFFSET`
      and `FILTER`/`FOCUSPOS` (flats) match the lights; Siril calibrates the lights
      with them (no dust donuts left, no amp glow).
- [ ] Notes, with every finding as an issue or a next stage; mark the exits that
      passed in each phase's plan with a line on the result.
