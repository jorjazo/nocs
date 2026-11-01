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

## The `nocs-appliance` package

`packaging/deb/build.sh` also builds `nocs-appliance_<version>_all.deb`
([`appliance/build.sh`](appliance/build.sh)): configuration only, which makes a box
the NOCS appliance. The Pi image installs it; a PC never gets it unless someone asks
for it. Shipping it as a package means a flashed box gets fixes to these settings by
updating ([ADR 0025](../docs/adr/0025-packaging-and-updates.md)).

| What | Where |
|---|---|
| NetworkManager runs the network (nocs-system runs the access point and the fallback, [ADR 0028](../docs/adr/0028-networking.md)); systemd-networkd disabled on install | `/usr/lib/netplan/01-nocs-network-manager.yaml`, `/usr/lib/NetworkManager/conf.d/nocs.conf` |
| A firewall that keeps indiserver and PHD2 to the box | `nocs-firewall.service`, `/usr/share/nocs-appliance/firewall.nft` |
| nocsd on port 80 | a drop-in for `nocsd.service` |
| Every operation of nocs-system | `/etc/nocs/system.conf.d/appliance.conf` |
| unattended-upgrades only downloads, needrestart only lists | `/etc/apt/apt.conf.d/52nocs-unattended-upgrades`, `/etc/needrestart/conf.d/nocs.conf` |
| A USB GPS as chrony's reference clock ([ADR 0029](../docs/adr/0029-system-time-and-site.md)) | a drop-in for `gpsd.service`, `/etc/chrony/conf.d/nocs-gps.conf` |
| The hardware watchdog ([ADR 0030](../docs/adr/0030-supervision.md)) | `/usr/lib/systemd/system.conf.d/nocs-appliance-watchdog.conf` |
| `_http._tcp` over mDNS; SSH with keys only | `/etc/avahi/services/nocs.service`, `/etc/ssh/sshd_config.d/50-nocs.conf` |

Network changes take effect at the next boot, so installing it never cuts off
whoever is connected. `test.sh` installs it after `nocs` when given its path.

## The Raspberry Pi image

```sh
sudo packaging/image/build.sh packaging/out/nocs_<version>_arm64.deb
```

On arm64 only (CI: the Image workflow, on an `ubuntu-24.04-arm` runner), as root,
with `nocs-appliance` of the same version next to the `nocs` package. It takes
Ubuntu's own preinstalled server image for the Raspberry Pi (checked against its
`SHA256SUMS`), grows its root filesystem and, in a chroot that starts no services,
adds the INDI and PHD2 PPAs, installs `nocs`, `nocs-appliance`, INDI's drivers and
PHD2, puts ASTAP and D50 in `/opt/astap`, removes snapd, names the box `nocs`,
replaces the boot partition's `user-data` with one that creates no login user, and
empties the machine id and SSH host keys so each Pi makes its own.

[`smoke-test.sh`](image/smoke-test.sh) then boots the root filesystem with
`systemd-nspawn` in a throwaway overlay and checks the services, nocsd's health, a
driver started through the FIFO, PHD2 and D50. The outputs are
`nocs-<version>-pi5-arm64.img.xz`, its SHA-256 and a manifest of every package
in it. Write it with Raspberry Pi Imager ("Use custom"), whose customisation
(Wi-Fi, SSH key) cloud-init applies at first boot; booting it on a Pi 5, from a
microSD card and from a USB SSD, is checked by hand ([ADR 0026](../docs/adr/0026-raspberry-pi-image.md)).

## The apt repository

[ADR 0035](../docs/adr/0035-apt-repository-and-release-publishing.md): a signed
repository on Cloudflare R2, behind the domain in the repository variable
`NOCS_APT_URL`, with the suites `testing` (every push to `main`, the last 5 builds)
and `stable` (tags, the last 3), and the release images in `images/` (the last 2).

```sh
packaging/repo/test.sh          # publish throwaway packages to a directory; apt installs them
packaging/repo/new-key.sh       # once: the signing key, into the secret APT_SIGNING_KEY
```

[`publish.py`](repo/publish.py) keeps each suite's state in its own `Packages`
files: it downloads those, never the packages, uploads new packages first and the
signed indices last, and deletes what no suite names any more. The Packages
workflow runs it after the install tests (`publish.py debs`), the Image workflow
for tags (`publish.py image`), and both add their files to the tag's GitHub release.

To switch it on, the repository needs:

| Kind | Name | What |
|---|---|---|
| variable | `NOCS_APT_URL` | the public address, e.g. `https://apt.example.org` |
| secret | `R2_ENDPOINT` | `https://<account id>.r2.cloudflarestorage.com` |
| secrets | `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | the bucket and an R2 token that may write to it |
| secret | `APT_SIGNING_KEY` | set by `new-key.sh`, which also writes `repo/nocs-archive-keyring.asc` (commit it) |

The `nocs` package ships that public key in `/usr/share/keyrings/`, and an image
built with `NOCS_APT_URL` set names the repository in
`/etc/apt/sources.list.d/nocs.sources` (`stable` for a tag, `testing` otherwise).

