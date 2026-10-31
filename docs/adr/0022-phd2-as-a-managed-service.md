# 0022. PHD2 as a service configured by nocsd

Date: 2026-10-31 · Status: Proposed

## Context

ADR 0006 chose PHD2 for guiding, run as a process managed by nocsd and driven
through its JSON-RPC event server. Phase 4 has to decide who starts it, how it
gets the rig's equipment and optics, and how a change reaches it. Facts from the
[spike](../spikes/phd2-headless.md) and from stage 4.1:

- PHD2 is a GUI application. It runs headless on Xvfb, started by a small script
  (`xvfb-run` hung as PID 1). An Xvfb killed with its lock file left behind
  refuses to start again on the same display, and after a power cut PHD2's own
  single-instance lock can name a live process, which leaves PHD2 waiting on an
  invisible dialog.
- The API cannot create profiles or choose equipment. `phd2 -l <file>` imports a
  settings file (`key<TAB>1<TAB>value` lines) and exits; PHD2 must then be
  started again. **The import replaces every PHD2 profile**, calibration
  included.
- PHD2 keeps a calibration per profile and restores it on connecting when
  `AutoLoadCalibration` is set; without that, a restart forgets it. Calibrating
  takes 40–70 s on the simulators, and minutes under a real sky.
- The `shutdown` method makes PHD2 exit cleanly; a supervisor that restarts it
  then gives a fresh PHD2 in a few seconds.
- PHD2 connects to indiserver itself. Its address is the one PHD2 sees (`indi`
  inside the development network, `localhost` on the Pi), not always nocsd's.
- `set_connected false` disconnects PHD2 from indiserver but leaves the devices
  connected (the simulators, and the ZWO ASI220MM Mini and AM7 on the lab Pi).
- The pixel size has to match the guide camera, or PHD2 raises an alert;
  NOCS reads it from the camera (`CCD_INFO`) once it is connected. The focal
  length comes from the guiding train: a guide scope's optics, or the imaging
  optics for an off-axis guider or a guide sensor built into the main camera.
- PHD2 needs ~100 MiB and ~3 % of a Pi 5's CPU while guiding.

Options considered for who runs PHD2:

1. **nocsd spawns Xvfb and PHD2 as child processes.** nocsd controls every
   start, but takes on process supervision, and guiding stops whenever nocsd
   restarts.
2. **PHD2 runs as its own service** (a container in development and CI, a
   systemd unit on the Pi), restarted by its supervisor when it exits. nocsd
   writes the settings file and asks PHD2 to shut down to apply it. This is the
   same split as indiserver (ADR 0011): one code path everywhere, and guiding
   carries on while nocsd restarts.
3. **NOCS uses whatever PHD2 is running, as the user set it up.** Right for a
   PC where the user runs PHD2's own window, but it is not the appliance.

## Decision

- **PHD2 is an external service** (option 2), started by
  [`dev/phd2/entrypoint.sh`](../../dev/phd2/entrypoint.sh): it clears stale
  display and instance locks, starts Xvfb, imports the settings file named by
  `PHD2_SETTINGS` **only when it differs from the one imported last**, and runs
  PHD2. A container restart policy or `Restart=always` brings it back after
  `shutdown`. nocsd reaches it at `NOCS_PHD2_HOST`:`NOCS_PHD2_PORT`
  (default `localhost:4400`).
- **nocsd owns the settings** when `NOCS_PHD2_SETTINGS` names the file (as nocsd
  sees it). For the active profile, once the guide camera and the mount are
  ready, nocsd renders one PHD2 profile:
  - indiserver as PHD2 reaches it (`NOCS_PHD2_INDI_HOST`/`NOCS_PHD2_INDI_PORT`,
    defaulting to nocsd's own);
  - the guide camera and the mount by INDI device name (pulse guiding through
    the mount);
  - the guide camera's pixel size, and the guiding focal length (with the
    reducer);
  - the calibration step, as PHD2's calibration assistant computes it: 25 px in
    12 steps at declination 0, at the mount's guide rate (`GUIDE_RATE`, 0.5×
    sidereal when the mount does not say);
  - `AutoLoadCalibration` on, multi-star guiding on, 2 s exposures.

  The profile's name carries a hash of its contents. When the name PHD2 reports
  is not the one expected, nocsd writes the file and calls `shutdown`; PHD2
  comes back with the new settings. It never does this while PHD2 is looping,
  calibrating or guiding: the change waits until PHD2 stops.
- **One PHD2 profile at a time.** The import replaces every PHD2 profile, so
  keeping one per NOCS profile would not keep their calibrations anyway. A
  calibration survives restarts of PHD2 and of nocsd, and is lost when the
  settings change (other devices or optics, which make it invalid anyway) or
  when another NOCS profile is connected.
- **Without `NOCS_PHD2_SETTINGS`, nocsd adopts PHD2 as it is** (option 3, for a
  PC): it uses the profile the user selected, and reports equipment that does
  not match the NOCS profile instead of changing it.
- The `guiding` state shows whether PHD2 is reachable, its version and state,
  whether its settings are NOCS's, and why not.

## Consequences

- Development, CI and the Pi share the same entrypoint. The dev container reads
  the settings from `dev/.run/`, which nocsd writes into; the Pi gets a
  `phd2@.service` unit like indiserver's.
- A new train or a different guide camera costs a PHD2 restart (seconds) and a
  calibration. Switching between two rigs recalibrates each time.
- PHD2 settings that NOCS does not write (guiding algorithms and their
  parameters) keep PHD2's defaults, and anything a user changes in PHD2's window
  is lost at the next import. Exposing algorithm settings, if ever needed, goes
  through the API's `set_algo_param`, not the file.
- An off-axis guider and a built-in guide sensor are the same case for NOCS:
  the guiding train takes the imaging optics.
- PHD2's event server listens on every interface and has no authentication,
  like indiserver: anyone on the network can drive guiding and pulse the
  mount. The appliance's firewall (phase 6) must close both ports to the
  network.
- Phase 6 packages PHD2 and the unit with the Pi image; until then the lab Pi
  installs them by hand.
