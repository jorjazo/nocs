# Phase 6 plan — Appliance

Status: in progress (6.1–6.5 implemented; ADRs proposed) · Last updated: 2026-10-31 · Roadmap: [Phase 6](../roadmap.md#phase-6--appliance)

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
| 6.0 | Decisions | This plan; ADRs 0025–0030 | Review | 4–5 h | Proposed |
| 6.1 | The `nocs` package | `.deb` with its own Python (uv, python-build-standalone) in `/opt/nocs`, the web app, units for nocsd, indiserver and PHD2 run as the system user `nocs`, `/etc/nocs`, `/var/lib/nocs`; built in CI for amd64 and arm64 ([ADR 0025](../adr/0025-packaging-and-updates.md)) | Installs on a clean Ubuntu 26.04 container; nocsd answers and connects to indiserver | 8–10 h | Implemented: `packaging/deb/`, checked with systemd in a container on amd64 (116 MB package, 478 MB installed); arm64 in CI |
| 6.2 | Raspberry Pi image | The official Ubuntu image changed in a chroot on an arm64 runner: INDI and PHD2 from their PPAs, `nocs`, ASTAP with D50, NetworkManager; smoke test in `systemd-nspawn` ([ADR 0026](../adr/0026-raspberry-pi-image.md)) | Boots on a Pi 5 from microSD and from a USB SSD; nocsd reachable | 10–14 h | Implemented: `packaging/image/` and the Image workflow; the image builds and passes its smoke test in CI. Booting it on a Pi 5 waits for a Pi that no other work needs |
| 6.3 | nocs-system | The privileged helper: Unix socket, peer credentials, a closed list of operations, nocsd's client; reboot, power off (and the Pi 5's power button), host name ([ADR 0027](../adr/0027-nocs-system.md)) | Unit tests with fake tools; reboot from the app on a test Pi | 5–7 h | Implemented: `nocs.system` (helper, client, `nocs-system call`), `system` state, `POST /api/system/reboot` and `/poweroff` (refused while a job runs unless forced), `PUT /api/system/hostname`; packaged and checked in the container. Buttons come with the System screen (6.4); reboot, power off and the Pi 5's button are still to check on a test Pi |
| 6.4 | Health and diagnostics | nocsd reads temperatures, under-voltage, throttling, memory and the system disk without privileges; `system` state; "This computer" on the Rig screen; a diagnostics bundle (logs, versions) to download | Simulated `/sys`; the lab Pi read-only | 5–7 h | Implemented: `system.health` every 5 s, rounded (CPU temperature, fan, under-voltage and when it was last seen, throttling from cpufreq, memory, system disk, warnings); `GET /api/system/diagnostics`; "This computer" on Rig with restart, shut down and rename. Checked in a browser against fake tools; on the Pi when the image exists |
| 6.5 | Storage manager | USB drives mounted when plugged in, ejected from the app after a sync; eject refused while a frame is being written | A USB drive on a test Pi | 5–6 h | Implemented: `storage.mount` / `storage.eject` in nocs-system (`systemd-mount` at `/media/nocs/<UUID>`, owned by `nocs` on FAT/exFAT/NTFS, then `udisksctl power-off`); nocsd mounts drives as they are plugged in, lists the ones it cannot mount with the reason, does not mount an ejected one again while it stays plugged in, and refuses to eject while a frame is being saved to it (and while a job runs, unless forced); USB drives with Eject on Rig. Checked with fake tools and a fake `/sys`; a real drive waits for a test Pi |
| 6.6 | Network | Access point `NOCS-xxxx`, joining a network from the app with a fallback, Ethernet, country, firewall closing indiserver and PHD2 to the network, nocsd on port 80, SSH off by default ([ADR 0028](../adr/0028-networking.md)) | Phones (iOS, Android) on the access point and on home Wi-Fi; the fallback when the network goes | 12–16 h | |
| 6.7 | First boot | Presets from Raspberry Pi Imager (cloud-init) or a file on the boot partition; first run asks for the access point's password, the country, the name, time and site, storage and home Wi-Fi; `_http._tcp` over mDNS | Fresh image to first frame from a phone | 6–8 h | |
| 6.8 | Time and site | chrony sets the system clock from NTP, a USB GPS (gpsd) or the client; the GPS site is offered to the profile ([ADR 0029](../adr/0029-system-time-and-site.md)) | Pi without network or RTC battery; a USB GPS | 6–8 h | |
| 6.9 | Supervision | Spike (a frozen driver and indiserver); detection of hung indiserver, drivers and PHD2; recovery ladder; nocsd's systemd watchdog; the hardware watchdog ([ADR 0030](../adr/0030-supervision.md)) | Simulators frozen with `SIGSTOP`; a camera unplugged mid-exposure | 8–10 h | |
| 6.10 | Updates | Signed apt repository with `stable` and `testing`; update from the app only when asked and never during a job; OS updates downloaded, not installed by themselves; rollback to the previous version | Update a test Pi from one build to the next and back | 8–10 h | |
| 6.11 | User documentation | Quick start, supported hardware (tested, and anything INDI supports), troubleshooting, PC install | Someone else follows the quick start | 6–8 h | |
| 6.12 | Release | Release candidate, field test with a freshly flashed Pi, v0.1 | Exit criterion | 4–6 h + a night | |

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

## Open questions

- A Pi 5 for the stages that change a Pi's network and services (a second Pi, a
  spare microSD or SSD for the lab Pi in an agreed window, or Ethernet to the lab
  Pi so its Wi-Fi can be tested while SSH stays up).
- Hosting for the image (over 2 GiB compressed, more than GitHub Releases takes per
  file) and the apt repository.
- Whether to trim v0.1 (USB GPS, the PC apt repository, automatic recovery beyond
  restarting drivers) to come closer to the roadmap's estimate.

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
