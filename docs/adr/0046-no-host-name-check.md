# 0046. No host name check: any name reaches the box, pairing guards it

Date: 2026-11-14 · Status: Proposed · Amends: [ADR 0014](0014-authentication-and-pairing.md) (removes its host name check)

## Context

ADR 0014 was amended to refuse every request whose `Host` was not an IP address,
`localhost`, a `*.local` name or a name listed in `NOCS_HOSTNAMES`, against DNS
rebinding: a page on an attacker's domain, rebound to the box's address, is
same-origin with itself and passes the Origin check.

In use, the check refused the names people really reach a box by: a Tailscale
MagicDNS name (`nocs-lab.<tailnet>.ts.net`), a router's `nocs.lan`, a reverse
proxy. Each one needed an edit of `/etc/nocs/nocsd.env` and a restart, found
through a JSON error. Without the check, a page the owner has open, rebound to
the box's address, can do what a client on the box's network can do without
pairing:

- **After setup, it cannot command the box.** The owner's cookie belongs to the
  name the browser paired with, so the attacker's name has none: every owner
  endpoint and WebSocket is refused. Pairing needs the passphrase.
- **It can lock pairing out.** The passphrase throttle is one for the whole box,
  not one per client (up to 60 s after repeated failures): a page that keeps
  sending wrong passphrases blocks pairing and passphrase changes for as long as
  it stays open. Paired devices keep working.
- **With observer access on** (off by default), it can read what observers see:
  the state and previews, which include the saved sites' coordinates, a GPS fix
  and the name of the Wi-Fi network the box joined, and send them off the network.
- **In setup mode it can take the box.** Between installing and setting the
  passphrase, it can set the passphrase itself and become the owner: every owner
  endpoint, nocs-system's operations (network, host name, reboot) included. The
  real owner is locked out until `auth.json` is removed. That needs the owner's
  browser on a hostile page during those minutes, and an attack written for NOCS.
- Rebinding attacks in the wild sweep private addresses for popular software
  without authentication. Browsers are also restricting public pages' requests to
  private addresses (Private Network Access, now Local Network Access).
- Comparable systems (StellarMate, ASIAIR, INDIGO's web apps, N.I.N.A.) do no such
  check, and most have no authentication at all.

## Decision

- nocsd accepts any `Host`. `NOCS_HOSTNAMES` and the `421` refusal are removed.
- Authentication (passphrase, a cookie per paired device) and the Origin check of
  ADR 0014 stay as they are.

## Consequences

- A box works by any name that reaches it, with nothing to configure. Each name
  still needs its own pairing (ADR 0014).
- The three risks above are accepted. The box should be set up right after it is
  installed; HTTPS (phase 6) could close the setup window later if it ever matters.
- Observer access now also shares its view with any page the owner opens: the
  owner's location in the state is a reason to keep it off, or to leave it out of
  what observers see.
