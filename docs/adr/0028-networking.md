# 0028. Appliance networking: access point, station, fallback, names and firewall

Date: 2026-10-31 · Status: Proposed

## Context

In the field there is usually no network but the one the box makes; at home the
box should join the home Wi-Fi so the phone keeps its internet (design §11).
Facts that shape the decision:

- Ubuntu Server for the Pi configures the network with netplan and
  **systemd-networkd**, which has no access point mode. **NetworkManager** does:
  a Wi-Fi connection in `ap` mode with `ipv4.method shared` runs DHCP and DNS
  (dnsmasq) for its clients and keeps station connections side by side. netplan
  can hand the network to NetworkManager.
- The Pi 5's Wi-Fi (brcmfmac) supports access point mode; an access point and a
  station at once only on the same channel (`#channels <= 1` on the lab Pi), so
  running both is fragile: the box is either one or the other on Wi-Fi.
  Ethernet is independent.
- An access point needs a regulatory country, or the radio may refuse channels.
- A phone on a network without internet warns about it, and may send its own
  traffic over mobile data, but keeps the local network's subnet on Wi-Fi.
  Browsers on some phones do not resolve `.local` names by mDNS.
- A pairing belongs to the host name the browser used (ADR 0014): a phone that
  reaches the box as `nocs.local` at home and as `10.42.0.1` in the field needs two
  pairings.
- indiserver (port 7624) and PHD2's event server (4400) listen on every interface
  without authentication (ADR 0022): anyone on the network could drive the mount.
- nocsd listens on port 8000; ports below 1024 need `CAP_NET_BIND_SERVICE`.
- Several boxes may share a network; avahi renames a clashing name (`nocs-2`).

## Decision

- **NetworkManager runs the appliance's network** (`nocs-appliance` switches
  netplan's renderer and disables systemd-networkd). nocs-system changes it
  (ADR 0027); nocsd reads its state.
- **Access point:** SSID `NOCS-xxxx` (the last four hex digits of the Pi's serial
  number), WPA2, address `10.42.0.1/24`, 2.4 GHz on a channel valid for the
  country. Its password starts as a **fixed default, printed in the quick start**;
  the first run makes the owner change it (and the country) before anything else.
  The access point's DNS answers `<hostname>.local` and `<hostname>` with
  `10.42.0.1`, so phones that do not speak mDNS still find the box by the same name
  they use at home. There is no captive portal and no fake internet: the quick
  start says to stay on the network when the phone warns.
- **Station:** the owner adds networks from the app. Joining one is
  **test-and-revert**: the app says that the phone must follow the box to that
  network, nocs-system activates it and waits up to 45 s for an address; if none
  comes, the access point comes back.
- **Fallback**, run by nocs-system every 10 s:
  - at boot, known networks are tried for 60 s, then the access point starts;
  - when the station loses its network for 30 s, the access point starts;
  - while it is an access point, the box looks for known networks every 5 minutes,
    **only while no client is associated**, so a phone on it is never cut off;
  - the owner can pin either mode.
- **Ethernet** is always on, by DHCP with a link-local fallback.
- **Names:** host name `nocs` by default, changed from the app (ADR 0027); avahi
  publishes `<hostname>.local` and an `_http._tcp` service. The app shows when
  avahi had to rename the box, and every screen that shows an address shows the
  name, not the IP.
- **nocsd listens on port 80** on the appliance (`CAP_NET_BIND_SERVICE` in its
  unit); a PC keeps 8000 (ADR 0025).
- **Firewall** (nftables, from `nocs-appliance`): incoming traffic is allowed to
  port 80, mDNS, DHCP and DNS on the access point, ICMP, and SSH when it is on;
  indiserver's and PHD2's ports are reachable only from the box itself. An owner
  who wants KStars or another INDI client on the network switches "INDI clients
  on the network" on, which opens 7624 alone.
- **SSH is off by default.** It is switched on with a public key, from the app or
  from Imager's presets (ADR 0026); password logins are never enabled.
- **No HTTPS in v0.1.** The limits of plain HTTP stay as ADR 0014 lists them
  (no geolocation, no offline installation, no wake lock); HTTPS comes with remote
  access.

## Consequences

- A box always becomes reachable: on its access point if nothing else works, by
  the same name everywhere.
- Moving the box to a new network from the phone loses the connection for a
  moment, and the phone has to follow it. If the box cannot join, it comes back as
  an access point within a minute.
- A box at home that loses the home Wi-Fi during a session becomes an access
  point; the session goes on regardless (design §2), and the box rejoins the home
  network once no phone is on its access point.
- Credentials cross the access point protected only by its WPA2 password, which is
  why the first run changes it.
- On a PC nothing of this applies: `nocs` alone leaves the network to its owner.
