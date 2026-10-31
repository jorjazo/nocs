# 0026. Raspberry Pi image

Date: 2026-10-31 · Status: Proposed

## Context

v0.1 is an image that anyone writes to a microSD card or a USB SSD and boots on a
Raspberry Pi 5 (design §12). Facts that shape how it is built:

- Canonical publishes **Ubuntu Server 26.04 preinstalled for the Raspberry Pi**
  (`ubuntu-26.04.1-preinstalled-server-arm64+raspi.img.xz`, 1.53 GB). The lab Pi
  runs it: its kernel, firmware, `flash-kernel` and trial boot of new kernels
  (`[tryboot]` in `config.txt`), cloud-init on first boot, netplan with
  systemd-networkd, snapd.
- Raspberry Pi Imager writes any `.img.xz` and, for images that declare
  cloud-init, the user's presets (Wi-Fi, host name, SSH key) into the boot
  partition, where Ubuntu's cloud-init reads them.
- The **ASTAP database must be in the image**: SourceForge throttles long
  downloads to tens of kB/s, and a first boot often has no network at all
  ([spike](../spikes/pi5-performance.md)). D50 takes 874 MB and barely compresses
  (ADR 0018). With INDI's third-party drivers (`indi-3rdparty-libs`, 208 MB) and
  `nocs` (ADR 0025) the image is about 2.6–2.9 GB compressed: **more than the
  2 GiB per file that GitHub Releases accepts**.
- GitHub offers arm64 runners for public repositories: an arm64 image can be
  built natively, without emulating every package's install scripts under QEMU.
  QEMU does not emulate a Pi 5, so only a real Pi proves that the image boots.
- The image redistributes software NOCS does not write: INDI's third-party drivers
  (some embed vendor SDKs, such as ZWO's), PHD2, ASTAP and its star database.

Options considered:

1. **Change the official image**: loop-mount it, install and configure in a
   chroot, shrink and compress. What runs is what the lab Pi already runs.
2. **Build from scratch** with `ubuntu-image` (a classic image definition) or
   `debos`/`mkosi`. More control, but the Pi's boot assets, kernel and
   `flash-kernel` setup become NOCS's to maintain, and the result drifts from
   Canonical's tested image.
3. **Install at first boot**, as the lab kit does (`dev/pi/flash.sh`). Needs the
   internet and 10–20 minutes, and fails exactly where the appliance is used.

## Decision

- **Option 1.** `packaging/image/build.sh` downloads the official image, checks
  it against Ubuntu's `SHA256SUMS`, grows the file and its root partition, and
  works in a chroot of it with a `policy-rc.d` that starts nothing:
  - adds the INDI and PHD2 PPAs and the NOCS repository (ADR 0025);
  - installs `nocs`, `nocs-appliance`, `indi-bin`, `indi-3rdparty-drivers`,
    `phd2`, `xvfb`, `network-manager`, `gpsd` and `avahi-daemon`;
  - puts ASTAP's command-line solver and D50 in `/opt/astap` (downloaded once by
    CI and cached by checksum);
  - removes snapd, keeps cloud-init (Imager's presets), configures
    unattended-upgrades to only download (ADR 0025);
  - creates **no login user and no password**: SSH stays off until a key is given
    through Imager, cloud-init or the app (ADR 0028);
  - empties `/etc/machine-id` and removes SSH host keys, so each Pi makes its own
    at first boot.

  It then zeroes the free space and compresses with `xz`. Outputs:
  `nocs-<version>-pi5-arm64.img.xz`, its SHA-256 and a manifest of every package
  and version in it.
- CI builds the image on an arm64 runner for tagged releases and on demand, and
  runs a **smoke test** in `systemd-nspawn` on the root filesystem: the units
  start, nocsd answers, indiserver starts a simulator through the FIFO, ASTAP
  finds D50.
- **Boot tests are manual**, on a Pi 5 that no other work depends on, from a
  microSD card and from a USB SSD, before each release.
- **Booting from a USB SSD** is the same image written to the SSD. The Pi 5's
  bootloader tries the SD card first, then NVMe, then USB; the documentation says
  to remove the card and, on an old bootloader, to update it.
- **Hosting:** the image is published with the apt repository's files on a host
  that takes files over 2 GiB, chosen in stage 6.10; GitHub Releases carries the
  checksums and the manifest and links to it.
- Before the first public image, the licenses of everything it redistributes are
  checked and listed in the documentation, with the acknowledgements ASTAP ships
  with its databases.
- `dev/pi/flash.sh` stays the lab's tool until the image can replace it.

## Consequences

- The image follows Canonical's: a new Ubuntu point release, kernel or firmware
  comes in by rebuilding, and Ubuntu's own updates keep working on a flashed Pi.
- The build needs root, loop devices and about 12 GB of disk on the runner.
- An image without D50, small enough for GitHub Releases, would not solve dense
  Milky Way fields (ADR 0018); NOCS ships one image, with D50.
- Every image is tested on hardware by hand; nothing automatic proves that a Pi
  boots it.
- Users who customise the image with Imager get their Wi-Fi and SSH key on the
  first boot; the rest start from the access point (ADR 0028).
