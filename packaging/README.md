# Packaging

How NOCS is packaged for PCs and for the Raspberry Pi image
([ADR 0025](../docs/adr/0025-packaging-and-updates.md),
[ADR 0026](../docs/adr/0026-raspberry-pi-image.md)). Plan and status:
[phase 6](../docs/v0.1/phase-6.md).

## The `nocs` package

```sh
packaging/deb/build.sh                                  # web app + .deb into packaging/out
packaging/deb/test.sh packaging/out/nocs_*_amd64.deb    # install on Ubuntu 26.04 with systemd
```

`build.sh` builds the web app with pnpm, then the package in an Ubuntu 26.04
container (`deb/Containerfile`) for this machine's architecture: CI builds arm64 on
an arm64 runner. uv installs CPython 3.13 in `/opt/nocs/python` and nocsd's locked
dependencies in `/opt/nocs/venv`, created at those paths so nothing has to be
rewritten. `test.sh` installs the package with INDI and PHD2 from their PPAs in a
container that runs systemd (`--privileged`), and checks that nocsd answers and is
connected to indiserver, that a driver starts through the FIFO, that nocsd reaches
nocs-system and cannot reboot a PC, that PHD2 listens, and that an upgrade
restarts nocsd but not indiserver.

What it installs:

| Path | What |
|---|---|
| `/opt/nocs/python`, `/opt/nocs/venv` | nocsd and its own Python |
| `/opt/nocs/web` | the web app |
| `/opt/nocs/libexec/nocs-phd2` | PHD2's entrypoint ([dev/phd2/entrypoint.sh](../dev/phd2/entrypoint.sh)) |
| `nocsd.service`, `nocs-indiserver.service`, `nocs-phd2.service` | run as the system user `nocs`; nocsd starts the other two |
| `nocs-system.service` | the privileged helper, as root, on `/run/nocs-system/socket` ([ADR 0027](../docs/adr/0027-nocs-system.md)) |
| `/etc/nocs/nocsd.env` | settings (`NOCS_*`), kept across upgrades |
| `/etc/nocs/system.conf` | what nocs-system may do: nothing on a PC by default |
| `/var/lib/nocs` | profiles and `auth.json` (`config/`), catalog, previews, frames; kept on purge |
| `/run/indi/fifo` | indiserver's driver FIFO |

Installing it by hand on a PC, until the apt repository exists:

```sh
sudo add-apt-repository ppa:mutlaqja/ppa
sudo add-apt-repository ppa:pch/phd2
sudo apt install ./nocs_<version>_amd64.deb indi-3rdparty-drivers phd2 xvfb
# http://<this computer>:8000; logs: journalctl -u nocsd -u nocs-indiserver -u nocs-phd2
# what nocs-system offers here (as nocs): sudo -u nocs /opt/nocs/venv/bin/nocs-system call hello
```

ASTAP and its star databases are installed as [ADR 0018](../docs/adr/0018-plate-solving-with-astap.md)
says, in `/opt/astap`. Versions between releases are `<version>~git<commits>.g<commit>`,
which sort before `<version>`: bump `server/pyproject.toml` right after tagging a
release.

## The Raspberry Pi image

```sh
sudo packaging/image/build.sh packaging/out/nocs_<version>_arm64.deb
```

On arm64 only (CI: the Image workflow, on an `ubuntu-24.04-arm` runner), as root.
It takes Ubuntu's own preinstalled server image for the Raspberry Pi (checked
against its `SHA256SUMS`), grows its root filesystem and, in a chroot that starts no
services, adds the INDI and PHD2 PPAs, installs `nocs`, INDI's drivers, PHD2 and
avahi, chrony and gpsd (a USB GPS as chrony's reference clock, ADR 0029), puts
ASTAP and D50 in `/opt/astap`, switches every operation of nocs-system on
(`/etc/nocs/system.conf.d/appliance.conf`), removes snapd, makes unattended-upgrades
only download and needrestart only list, names the box `nocs`, replaces the boot
partition's `user-data` with one that creates no login user, and empties the
machine id and SSH host keys so each Pi makes its own.

[`smoke-test.sh`](image/smoke-test.sh) then boots the root filesystem with
`systemd-nspawn` in a throwaway overlay and checks the services, nocsd's health, a
driver started through the FIFO, PHD2 and D50. The outputs are
`nocs-<version>-pi5-arm64.img.xz`, its SHA-256 and a manifest of every package
in it. Write it with Raspberry Pi Imager ("Use custom"), whose customisation
(Wi-Fi, SSH key) cloud-init applies at first boot; booting it on a Pi 5, from a
microSD card and from a USB SSD, is checked by hand ([ADR 0026](../docs/adr/0026-raspberry-pi-image.md)).
The image also hands the network to NetworkManager (nocs-system runs the access
point and the fallback, ADR 0028), loads an nftables firewall that keeps indiserver
and PHD2 to the box, serves nocsd on port 80, takes SSH keys only, and turns the
hardware watchdog on. `nocs-appliance`, a later stage, will take this configuration
over from the script.
