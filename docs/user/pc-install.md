# Installing on a PC

NOCS runs on any computer with **Ubuntu 26.04** (amd64 or arm64), for example a mini
PC at the telescope. On a PC, NOCS leaves the network, the clock and the drives to
the computer's owner: it does not make a Wi-Fi access point, and the web app cannot
reboot or rename the computer.

## Install

```sh
sudo add-apt-repository ppa:mutlaqja/ppa     # INDI and its drivers
sudo add-apt-repository ppa:pch/phd2         # PHD2
sudo curl -fsSL -o /usr/share/keyrings/nocs-archive-keyring.asc \
  https://apt.nocs.app/nocs-archive-keyring.asc
sudo tee /etc/apt/sources.list.d/nocs.sources <<'EOF'
Types: deb
URIs: https://apt.nocs.app
Suites: stable
Components: main
Signed-By: /usr/share/keyrings/nocs-archive-keyring.asc
EOF
sudo apt update
sudo apt install nocs indi-3rdparty-drivers phd2 xvfb
```

The package installs nocsd with its own Python in `/opt/nocs`, and runs nocsd,
indiserver and PHD2 as the system user `nocsd`. Open `http://<this computer>:8000`
(or <http://localhost:8000> on the computer itself) and set up as in the
[quick start](quick-start.md), step 3.

`stable` has the releases. `testing` has every build of the development branch
and may break: write `Suites: testing` instead to follow it. Until v0.1 is
released, only `testing` has packages. Do not install `nocs-appliance` on a PC:
it turns the computer into the Pi's appliance (its network, firewall and port 80).

Updates come with the computer's own `sudo apt upgrade`. The package keeps the
repository's key up to date in `/usr/share/keyrings/` when it changes.

## Plate solving

Install ASTAP's command-line solver and a star database (D50 for most telescopes)
from [ASTAP's site](https://www.hnsky.org/astap.htm) into `/opt/astap`, where NOCS
finds them. Without them, NOCS says so when a frame has to be solved.

## Settings

- `/etc/nocs/nocsd.env`: nocsd's settings (`NOCS_*`, listed in
  `server/src/nocs/config.py`): the port, and host names other than IP addresses
  and `*.local` (`NOCS_HOSTNAMES`). Then `sudo systemctl restart nocsd`.
- `/etc/nocs/system.conf`: what nocs-system may do for nocsd. On a PC, only
  restarting indiserver and PHD2.
- `/var/lib/nocs`: profiles, the passphrase, the frame catalog, and frames saved
  to the internal storage.

USB drives that the desktop mounts under `/media/<user>/` are only usable if the
`nocsd` user may write to them.

## Logs

```sh
journalctl -u nocsd -u nocs-indiserver -u nocs-phd2 -u nocs-system
```

indiserver's and PHD2's ports (7624, 4400) have no authentication: keep them behind
the PC's firewall unless you mean to use them from another computer.
