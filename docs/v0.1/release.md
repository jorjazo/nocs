# v0.1 release checklist

Stage 6.12 of [phase 6](phase-6.md). The exit criterion of the roadmap: **a fresh
Pi 5 flashed with the image runs a full night from a phone, with no other computer
involved.** No laptop and no SSH from flashing to packing up. If one is needed,
note why: that is a finding, and the release waits for its fix.

## Release candidate

- [ ] Phases 3–5 have passed their own field tests, and `main` has at least the
      sequence builder and the session monitor (5.13, 5.14). CI is green.
- [ ] The apt repository works ([ADR 0035](../adr/0035-apt-repository-and-release-publishing.md)):
      `testing` installs on a clean Ubuntu 26.04 PC with the [PC install](../user/pc-install.md)
      steps, and a test Pi updates from one `testing` build to the next and back.
- [ ] The licenses of everything the image redistributes are listed in the user
      documentation, with ASTAP's acknowledgements.
- [ ] The hardware checks left from stages 6.2–6.8, on the lab Pi booted from the
      spare SSD (take the lab lock; the lab's own card stays out meanwhile):
  - [ ] the image boots from microSD and from a USB SSD; nocsd answers;
  - [ ] the access point with an iPhone and an Android phone; joining the home
        network and falling back to the access point when it goes;
  - [ ] first boot with Raspberry Pi Imager's presets (Wi-Fi, host name, SSH key)
        and without them;
  - [ ] restart, shut down, the Pi 5's power button, rename;
  - [ ] a USB drive mounted, written to and ejected;
  - [ ] the clock without network or RTC battery: set from the phone, then from a
        USB GPS;
  - [ ] a hung driver (`kill -STOP`) and a hung indiserver are noticed and
        restarted; the power box cycles a camera under a sequence.
- [ ] The screens and names in the [user guide](../user/README.md) match the app.
- [ ] `server/pyproject.toml` says `0.1.0rc1`; tag `v0.1.0-rc.1`. The tag's
      packages reach `stable` and its image `images/` on the repository; the
      GitHub release has the notes, the packages, the image's checksum and link.
- [ ] Someone other than the maintainer follows the [quick start](../user/quick-start.md)
      from the release candidate's image.

## Field test: a night from a freshly flashed Pi

### Before going out

- [ ] The release candidate's image, downloaded from the link in the GitHub release
      and checked against its SHA-256, written with Raspberry Pi Imager to the spare
      SSD (or a microSD) with no presets.
- [ ] Nothing copied onto it by hand: no profile, no SSH key, no ASTAP files.
- [ ] A USB drive for the frames.

### At the site, all from the phone

1. **First boot.** Power the Pi. Join `NOCS-xxxx` with the password printed in the
   quick start, open `http://nocs.local` (or `http://10.42.0.1`), set the owner
   passphrase, the access point's country and own password. The phone joins
   again.
2. **Time and site.** The clock comes from the phone (or the GPS); the site from
   the phone's entry or the GPS.
3. **Profile.** Make the rig's profile in the app: every role, the optics, the
   site, filter names, which power box output feeds what. Connect it.
4. **Storage.** Plug the USB drive; it mounts and becomes the destination.
5. **Polar alignment, focus, guiding.** Polar align from three solves; autofocus;
   calibrate and guide with PHD2.
6. **Tonight.** Pick a target from Tonight; centre it by solving.
7. **Sequence.** Build a sequence until dawn with autofocus and dithering; start
   it, lock the phone, check it now and then. Note every recovery it makes.
8. **Morning.** The sequence parks the mount and warms the camera. Eject the drive
   from the app, then shut the Pi down from the app.

### After

- [ ] The frames on the drive open on a PC, with their FITS headers.
- [ ] The session report and the diagnostics bundle saved for the record.
- [ ] Findings written into [phase 6](phase-6.md). If none blocks: accept ADRs
      0025–0030 and 0035, tag `v0.1.0`, publish, announce.
