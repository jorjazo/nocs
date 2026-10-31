# Phase 2 field test

The exit criterion of [phase 2](phase-2.md): with AM5 + ZWO camera + EFW + EAF + PPBA
on the Pi 5, take a set of manual sub-frames **controlled only from a phone**. No
laptop and no SSH during the session. If one is needed, note why: that is a
finding, and the test is not passed.

## Before going out

- [ ] `main` has stages 2.8 (focuser, wheel, profile editor), 2.9 with the mount UI,
      2.10 (PPBA) and 2.11. CI is green.
- [ ] The Pi runs that commit: server (`uv sync`) and `web/dist` updated together,
      nocsd restarted, indiserver@ running with no extra drivers.
- [ ] A network for the phone and the Pi at the site (the hotspot needs nocs-system,
      phase 6): the phone's own hotspot or a travel router. The Pi joins it by
      itself, and the phone reaches `http://<pi>.local:8000` or the Pi's IP.
- [ ] The phone is paired as owner (ADR 0014). An observer device is optional.
- [ ] The rig profile, made in the profile editor:
  - every role: main camera, guide camera, mount, focuser, filter wheel, power box;
    serial ports by `/dev/serial/by-id/`;
  - imaging and guiding optics: focal length, aperture, reducer;
  - the site: name, latitude, longitude, elevation;
  - filter names.
- [ ] Storage destination: a USB drive mounted by fstab, or internal (microSD).
      There is room for the night.

## At the site, all from the phone

1. **Power and connect.** PPBA on. Connect the profile on the Rig screen; every
   role ends up ready. Switch on the outputs the rig needs, and the dew heaters.
2. **Time and site.** The mount gets the site, then the phone's time. The clock
   warning is gone, or frame times are corrected (ADR 0015).
3. **Cooling.** Set the camera's target (for example −10 °C) with a ramp. Watch
   the power and temperature while doing the rest.
4. **Mount.** Unpark. Go to a bright star or the target: J2000, refused below the
   horizon. Nudge it with the slew pad. The dead man's switch stops it when the
   finger lifts or the Wi-Fi drops.
5. **Framing.** Loop on the main camera, binned, with a short exposure. Zoom the
   preview and check the stars and HFR.
6. **Focus.** Move the EAF in absolute or relative steps while looping; HFR should
   fall to a minimum. Note the position and the focuser temperature.
7. **Filter.** Change the filter from the Live view; the preview and the frame
   folder follow it.
8. **Guide camera.** Switch the Live view to the guide camera; a loop of 1–2 s
   shows stars. Nothing is saved. Switch back. Guiding itself is phase 4.
9. **Sub-frames.** Set the target name, light frames, gain and offset, and the
   exposure. Turn Save on and take the set one by one with the shutter, for
   example 10 × 60–180 s, with the phone locked between frames.
10. **Check the frames.** They are in the frame list for the night with stars
    and HFR. Download one frame and the night's zip to the phone.
11. **End.** Cooler off (warm up with the ramp), park, outputs off, disconnect the
    profile.

## Afterwards, at home

- [ ] FITS headers of a light frame: `OBJECT`, `OBJCTRA`/`OBJCTDEC` against the
      target, `FILTER`, `FOCUSPOS`, `CCD-TEMP` and `SET-TEMP`, `GAIN`/`OFFSET`,
      `SITENAME`/`SITELAT`/`SITELONG`/`SITEELEV`, `FOCALLEN`/`APTDIA`, and `DATE-OBS`
      against the phone's time.
- [ ] The frames open and stack in Siril or PixInsight (Bayer pattern, row order).
- [ ] Notes: everything that needed a second try, a laptop or a workaround, and
      battery use (Pi and phone) over the session. These become issues or the
      next stages.
- [ ] Mark 2.11 done in [phase-2.md](phase-2.md) with a line on the result.
