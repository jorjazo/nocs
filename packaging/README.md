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
