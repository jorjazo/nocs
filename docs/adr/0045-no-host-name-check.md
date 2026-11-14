# 0045. No host name check: any name reaches the box, pairing guards it

Date: 2026-11-14 · Status: Proposed · Amends: [ADR 0014](0014-authentication-and-pairing.md) (removes its host name check)

## Context

ADR 0014 was amended to refuse every request whose `Host` was not an IP address,
`localhost`, a `*.local` name or a name listed in `NOCS_HOSTNAMES`, against DNS
rebinding: a page on an attacker's domain, rebound to the box's address, is
same-origin with itself and passes the Origin check.

In use, the check refused the names people really reach a box by: a Tailscale
MagicDNS name (`nocs-lab.<tailnet>.ts.net`), a router's `nocs.lan`, a reverse
proxy. Each one needed an edit of `/etc/nocs/nocsd.env` and a restart, found
through a JSON error. Looked at again, what the check protects is small:

- **After setup, a rebound page gets nothing it could not get anyway.** The owner's
  cookie belongs to the name the browser paired with, so the attacker's name has
  none: every owner endpoint answers 401. Pairing needs the passphrase, and
  attempts are throttled.
- **Observer access** (off by default) shows the state and previews: a night's
  session, which observer access exists to show.
- **Setup mode** is the one real gap: between installing and setting the
  passphrase, a rebound page could set it. That needs the owner's browser on a
  hostile page during those minutes, and an attack written for NOCS.
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
- The setup-mode window is accepted as a risk: the box should be set up right after
  it is installed. HTTPS (phase 6) could close it later if it ever matters.
- A rebound page can read what observers see when observer access is on.
