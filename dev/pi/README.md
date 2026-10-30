# Lab Raspberry Pi

`flash.sh` turns an SD card into a ready-to-use NOCS **lab** Pi: the official
Ubuntu Server image for Raspberry Pi plus a cloud-init setup that runs on first
boot. It is a development tool, not the end-user image (that is roadmap
phase 6: a pre-built image that works offline with its own hotspot).

cloud-init creates the user and installs `nocs-lab-setup.service`, which does
the rest as soon as the Pi has internet (Wi-Fi or Ethernet) and retries every
minute and at every boot until it completes, so a first boot without network is
harmless. It takes ~10–20 minutes and sets up:

- user `$USER` with your SSH public key, passwordless sudo, no password login;
- hostname `nocs-lab` (reachable as `nocs-lab.local` via mDNS);
- Wi-Fi from the network name and password you enter, plus Ethernet;
- Docker with Compose, git, uv and this repository in `~/nocs`;
- ASTAP command-line solver and the D50 star database in `/opt/astap`.

## Use

```sh
dev/pi/flash.sh                  # lists removable disks and SD cards
dev/pi/flash.sh /dev/mmcblk0     # write the card (asks Wi-Fi details and confirmation)
DRY_RUN=1 dev/pi/flash.sh        # download and show the setup, write nothing
```

The script downloads the newest Ubuntu 26.04.x Raspberry Pi server image to
`~/.cache/nocs/` and verifies it against Ubuntu's published SHA256 sums. It
refuses non-removable disks, partitions, disks with system mount points and
anything over 256 GB (override with `FORCE=1`), and writes only after you type
the device path back. Settings (`PI_USER`, `PI_HOSTNAME`, `WIFI_COUNTRY`,
`WITH_ASTAP`, …) are listed at the top of the script.

After first boot:

```sh
ssh nocs-lab.local              # needs the setup to have installed avahi
cat /var/lib/nocs-lab/ready     # written when the setup finished
journalctl -u nocs-lab-setup    # its progress / errors
```

The Wi-Fi password ends up in plain text on the card's boot partition, as with
Ubuntu's own Raspberry Pi setup.
