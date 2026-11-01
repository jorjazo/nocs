# Installing on a PC

NOCS runs on any computer with **Ubuntu 26.04** (amd64 or arm64), for example a mini
PC at the telescope. On a PC, NOCS leaves the network, the clock and the drives to
the computer's owner: it does not make a Wi-Fi access point, and the web app cannot
reboot or rename the computer.

## Install

```sh
sudo add-apt-repository ppa:mutlaqja/ppa     # INDI and its drivers
sudo add-apt-repository ppa:pch/phd2         # PHD2
sudo apt install ./nocs_<version>_amd64.deb indi-3rdparty-drivers phd2 xvfb
```

The package installs nocsd with its own Python in `/opt/nocs`, and runs nocsd,
indiserver and PHD2 as the system user `nocs`. Open `http://<this computer>:8000`
(or <http://localhost:8000> on the computer itself) and set up as in the
[quick start](quick-start.md), step 3.

Until the NOCS apt repository exists, the packages come from the project's release
page (or the Packages workflow's artifacts).

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
`nocs` user may write to them.

## Logs

```sh
journalctl -u nocsd -u nocs-indiserver -u nocs-phd2 -u nocs-system
```

indiserver's and PHD2's ports (7624, 4400) have no authentication: keep them behind
the PC's firewall unless you mean to use them from another computer.
