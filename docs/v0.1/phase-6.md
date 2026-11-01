# Phase 6 plan — Appliance

Status: in progress (6.1–6.8 and 6.11 done, 6.9 and 6.10 in part; ADRs proposed, open points decided) · Last updated: 2026-10-31 · Roadmap: [Phase 6](../roadmap.md#phase-6--appliance)

Goal: anyone flashes an image onto a Raspberry Pi 5 and runs a full night from a
phone, with no other computer involved. PC users install the same software from
`.deb` packages.

**Exit:** **v0.1 public release.** A fresh Pi 5 flashed with the image runs a full
night from a phone with no other computer involved.

Phases 3–5 are still being built while this one starts. The stages that only add
packaging, the system helper and new state come first; the ones that need every
other phase (supervision of a running sequence, the final image, the release)
come last. Stages that change a Pi's network or services are tested on a Pi that
no other session is using: the lab Pi stays as it is.

## Stages

| # | Stage | Contents | Check | Estimate | Status |
|---|---|---|---|---|---|
| 6.0 | Decisions | This plan; ADRs 0025–0030, 0035 | Review | 4–5 h | Proposed; hosting, keys, 6.9b and the test Pi decided 2026-10-31 |
| 6.1 | The `nocs` package | `.deb` with its own Python (uv, python-build-standalone) in `/opt/nocs`, the web app, units for nocsd, indiserver and PHD2 run as the system user `nocs`, `/etc/nocs`, `/var/lib/nocs`; built in CI for amd64 and arm64 ([ADR 0025](../adr/0025-packaging-and-updates.md)) | Installs on a clean Ubuntu 26.04 container; nocsd answers and connects to indiserver | 8–10 h | Implemented: `packaging/deb/`, checked with systemd in a container on amd64 (116 MB package, 478 MB installed); arm64 in CI |
| 6.2 | Raspberry Pi image | The official Ubuntu image changed in a chroot on an arm64 runner: INDI and PHD2 from their PPAs, `nocs`, ASTAP with D50, NetworkManager; smoke test in `systemd-nspawn` ([ADR 0026](../adr/0026-raspberry-pi-image.md)) | Boots on a Pi 5 from microSD and from a USB SSD; nocsd reachable | 10–14 h | Implemented: `packaging/image/` and the Image workflow; the image builds and passes its smoke test in CI. Booting it on a Pi 5 waits for a Pi that no other work needs |
| 6.3 | nocs-system | The privileged helper: Unix socket, peer credentials, a closed list of operations, nocsd's client; reboot, power off (and the Pi 5's power button), host name ([ADR 0027](../adr/0027-nocs-system.md)) | Unit tests with fake tools; reboot from the app on a test Pi | 5–7 h | Implemented: `nocs.system` (helper, client, `nocs-system call`), `system` state, `POST /api/system/reboot` and `/poweroff` (refused while a job runs unless forced), `PUT /api/system/hostname`; packaged and checked in the container. Buttons come with the System screen (6.4); reboot, power off and the Pi 5's button are still to check on a test Pi |
| 6.4 | Health and diagnostics | nocsd reads temperatures, under-voltage, throttling, memory and the system disk without privileges; `system` state; "This computer" on the Rig screen; a diagnostics bundle (logs, versions) to download | Simulated `/sys`; the lab Pi read-only | 5–7 h | Implemented: `system.health` every 5 s, rounded (CPU temperature, fan, under-voltage and when it was last seen, throttling from cpufreq, memory, system disk, warnings); `GET /api/system/diagnostics`; "This computer" on Rig with restart, shut down and rename. Checked in a browser against fake tools; on the Pi when the image exists |
| 6.5 | Storage manager | USB drives mounted when plugged in, ejected from the app after a sync; eject refused while a frame is being written | A USB drive on a test Pi | 5–6 h | Implemented: `storage.mount` / `storage.eject` in nocs-system (`systemd-mount` at `/media/nocs/<UUID>`, owned by `nocs` on FAT/exFAT/NTFS, then `udisksctl power-off`); nocsd mounts drives as they are plugged in, lists the ones it cannot mount with the reason, does not mount an ejected one again while it stays plugged in, and refuses to eject while a frame is being saved to it (and while a job runs, unless forced); USB drives with Eject on Rig. Checked with fake tools and a fake `/sys`; a real drive waits for a test Pi |
| 6.6 | Network | Access point `NOCS-xxxx`, joining a network from the app with a fallback, Ethernet, country, firewall closing indiserver and PHD2 to the network, nocsd on port 80, SSH off by default ([ADR 0028](../adr/0028-networking.md)) | Phones (iOS, Android) on the access point and on home Wi-Fi; the fallback when the network goes | 12–16 h | Implemented: `nocs.system.network` (one actor: the access point `NOCS-xxxx` with DNS for `<host>.local`, joining with test-and-revert, the fallback, pinned modes, country) and its `network.*` operations; `network` state and API; the image on NetworkManager with nftables (only 22, 80, mDNS, DHCP, DNS from outside), nocsd on port 80 and SSH by key only; Network on Rig. Checked against a simulated NetworkManager and in a browser; phones on a real access point wait for a test Pi |
| 6.7 | First boot | Presets from Raspberry Pi Imager (cloud-init) or a file on the boot partition; first run asks for the access point's password, the country, the name, time and site, storage and home Wi-Fi; `_http._tcp` over mDNS | Fresh image to first frame from a phone | 6–8 h | Implemented: after pairing, the owner sets the access point's country and own password, and may join a home network, before anything else (`POST /api/system/network/setup`; the access point restarts after the reply); Raspberry Pi Imager's presets (Wi-Fi, host name, SSH key) through cloud-init; `_http._tcp` over avahi. Checked in a browser; the whole first boot on a Pi waits for a test Pi |
| 6.8 | Time and site | chrony sets the system clock from NTP, a USB GPS (gpsd) or the client; the GPS site is offered to the profile ([ADR 0029](../adr/0029-system-time-and-site.md)) | Pi without network or RTC battery; a USB GPS | 6–8 h | Implemented: `time.set` in nocs-system; nocsd reads the clock's source (`chronyc -c sources`, else timedatectl) into `clock.source` and sets the clock from a client's report when nothing keeps it and no job runs; gpsd's fix in `gps`, `POST /api/gps/site` for the active profile and the mount; the image has gpsd (USB autodetect) and chrony reading it, and enables every operation of nocs-system (`/etc/nocs/system.conf.d/appliance.conf`). Checked with fake tools and a fake gpsd; a real GPS waits for a test Pi. nocsd remembers, across its restarts, that a client's time set the clock this boot (the boot's id in `/var/lib/nocs/clock-set-from-client`), so the time stays known and a sequence can resume (phase 5.12) |
| 6.9 | Supervision | Spike (a frozen driver and indiserver); detection of hung indiserver, drivers and PHD2; recovery ladder; nocsd's systemd watchdog; the hardware watchdog ([ADR 0030](../adr/0030-supervision.md)) | Simulators frozen with `SIGSTOP`; a camera unplugged mid-exposure | 8–10 h | Partly implemented: the spike (in ADR 0030); indiserver pinged every 10 s and, hung, restarted through nocs-system (`services.restart`, also from the app) and reconnected; nocsd under systemd's watchdog (`Type=notify`, 30 s); the hardware watchdog on in the image. Left for 6.9b, with the sequencer's recovery policies (ADR 0032): a device that stops answering, restarting its driver, and power cycling the output that feeds it as the `device` policy's escalation (never the mount; offered in the app outside a sequence). USB reset comes after v0.1 |
| 6.10 | Updates | Signed apt repository with `stable` and `testing`; update from the app only when asked and never during a job; OS updates downloaded, not installed by themselves; rollback to the previous version | Update a test Pi from one build to the next and back | 8–10 h | In part: nocs-system's `update` group (check with apt; install and roll back in a transient `nocs-update` unit, so that restarting nocs-system and nocsd does not kill apt; the previous NOCS reinstalled from apt's cache), `updates` state, the API (installing refused while a job runs, unless forced) and Updates on Rig; unattended-upgrades only downloads and needrestart only lists (6.2). `nocs-appliance` (configuration only: network, firewall as `nocs-firewall.service`, port 80, nocs-system's operations, the GPS, the watchdog), so a flashed Pi gets fixes to them by updating; the image installs it and a rollback puts it back too. The repository's tools ([ADR 0035](../adr/0035-apt-repository-and-release-publishing.md)): `packaging/repo/publish.py` (suites from their own indices, pruning, signing; images), `new-key.sh`, and the Packages and Image workflows publishing to R2 and to GitHub releases; checked against a local repository that apt on Ubuntu 26.04 installs from. Left: the maintainer's domain, bucket, token and key, then updating a test Pi from one `testing` build to the next and back |
| 6.11 | User documentation | Quick start, supported hardware (tested, and anything INDI supports), troubleshooting, PC install | Someone else follows the quick start | 6–8 h | Written: `docs/user/` (quick start, supported hardware, troubleshooting, PC install). Screens and names to check against the release; someone else following it waits for the release candidate |
| 6.12 | Release | Licenses of what the image redistributes; ADRs 0025–0030 and 0035 accepted; `v0.1.0-rc.1` (package `0.1.0~rc1`) published to `stable`; the hardware checks left from 6.2–6.8 on the lab Pi booted from a spare SSD; a night from a freshly flashed Pi with only a phone ([checklist](release.md)); v0.1 | Exit criterion | 4–6 h + a night | |

Total **87–115 h**, above the roadmap's 50–70 h. Not in v0.1 unless decided
otherwise: HTTPS on the LAN (a local certificate authority, 8–10 h), which would
bring geolocation, offline installation and wake lock (ADR 0014).

Order: 6.0 → 6.1 → 6.3 → 6.4 → 6.2 → 6.5 → 6.8 → 6.6 → 6.7 → 6.10 → 6.9 →
6.11 → 6.12.

- **Can start now** without touching what phases 3–5 change: 6.0–6.4. They add
  `packaging/`, `nocs.system` and new state (a small change to `api/schemas.py`).
- **Need a Pi of their own:** the boot test of 6.2, and 6.5–6.8. Switching the lab
  Pi's Wi-Fi to an access point would cut every session's SSH.
- **Wait for other phases:** the recovery half of 6.9 (it acts through the phase 5
  sequencer's recovery policies, and PHD2 must reconnect after indiserver restarts),
  the final image and 6.12 (after the field tests of phases 3–5).

## Decisions taken for this phase

- One package for PCs and the Pi, `nocs`; a second one, `nocs-appliance`, turns a
  box into the appliance (network, firewall, port 80, first boot) and is never
  installed on a PC by default (ADR 0025).
- indiserver, PHD2 and nocsd all run as the system user `nocs`, which writes the
  driver FIFO and reads the frames drivers save (ADR 0011, ADR 0012).
- nocsd reads everything it can without privileges; nocs-system only performs a
  closed list of privileged operations (ADR 0027).
- Nothing restarts behind a session: no unattended installs, no automatic service
  restarts after library upgrades, no network switch while a phone is on the
  access point.
- Decided 2026-10-31 by the maintainer:
  - **Hosting:** Cloudflare R2 behind a domain of the maintainer's, for the apt
    repository and the image; GitHub Releases carries notes, checksums and the
    link (ADR 0035).
  - **Signing key:** only in CI, rotated by shipping a new keyring in the package.
  - **Suites:** `testing` from every push to `main` (last 5 builds), `stable` from
    tags (last 3); no channel switch in the app in v0.1.
  - **6.9b:** driver restart and power cycling through the power box in v0.1, USB
    reset after it (ADR 0030).
  - **Test Pi:** a spare SSD or microSD for the lab Pi, booted in agreed windows,
    for the hardware checks and the release's field test; the lab's own card stays
    as it is.
  - Out of v0.1: HTTPS on the LAN, a channel switch in the app, listing NOCS in
    Raspberry Pi Imager.

## Open questions

- The domain for the repository, and the R2 bucket and its token (the
  maintainer's accounts).

## Measured

On the lab Pi (Ubuntu 26.04.1, kernel 7.0 raspi), read without changing anything:

- The network is netplan with **systemd-networkd**; NetworkManager is not installed
  (1.54 is in the archive). wlan0 is its only link.
- The Wi-Fi (brcmfmac) supports access point mode; an access point and a station
  at once only on one channel (`#channels <= 1`).
- `/dev/watchdog0` exists (`dtparam=watchdog=on`); the RTC (`rpi-rtc`) keeps time
  only with a battery; hwmon has `cpu_thermal`, `rpi_volt` (under-voltage) and
  `pwmfan`. `vcgencmd` cannot open `/dev/vcio`.
- chrony (`rtcsync`, `makestep 1 3`), avahi, udisks2 and snapd are installed, and
  **unattended-upgrades** with `apt-daily-upgrade.timer` are on.
- `config.txt` has `[tryboot] os_prefix=new/`: Ubuntu's own trial boot for kernel
  updates.
- Sizes: the official image is 1.53 GB as `.img.xz`; D50 takes 874 MB installed and
  barely compresses; `indi-3rdparty-libs` 208 MB; nocsd's environment 316 MB with
  its development tools.

The first image built by CI (`ubuntu-24.04-arm`, 14 minutes in all):

- The root filesystem holds 4.5 GB once INDI, PHD2, NOCS and D50 are in (2.8 GB in
  Ubuntu's image), so the build grows it by 3 GB; it is 7.1 GB raw before the first
  boot grows it to the card.
- Compressed with `xz -6`: **3.3 GB**.
- ASTAP and D50 downloaded from SourceForge in 23 s with the resume-on-a-new-
  connection trick, and are cached for later builds.
