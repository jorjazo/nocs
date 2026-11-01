# Remote access plan — NOCS from outside the local network

Status: proposed (decisions open, below) · Last updated: 2026-11-01 · Roadmap: [Beyond v0.1](../roadmap.md#beyond-v01-unordered-backlog) · Decision: [ADR 0037](../adr/0037-remote-access.md)

Goal: the owner reaches their box from anywhere: from the house while the rig
images in the garden on the home Wi-Fi, from the city while it runs at a dark site
on mobile data, to check the session, see the latest frame, park on clouds or start
tomorrow's sequence. Nothing is opened to the internet, nobody but the owner's own
devices can reach the box, and a slow or dropping link never leaves the rig moving.

**Exit (field):** with the box at a rural site on a 4G router (CGNAT) and the owner's
phone on mobile data in another city, the phone opens the box over HTTPS by its own
name, watches a sequence for an hour under a data budget (below), parks the mount,
and the owner turns remote access off from the app; the box then refuses any
connection from outside the site.

## What we start from

- nocsd serves plain HTTP on port 80 (appliance) or 8000 (PC). Every `/api` call
  needs a paired device cookie, except a short public and observer list; the host
  name check refuses names other than IP addresses, `localhost`, `*.local` and
  `NOCS_HOSTNAMES`; unsafe methods and WebSockets must be same-origin (ADR 0014).
- Wrong passphrases are throttled **globally**: after 5 failures each attempt waits
  for a delay doubling to 60 s. Paired devices keep working during a lockout.
- The appliance's firewall (`nocs-firewall.service`, `nocs-appliance`) lets in only
  22, 80, mDNS, DHCP and DNS (ADR 0028). indiserver and PHD2 are local only.
- nocs-system performs a closed list of privileged operations in groups switched on
  in `/etc/nocs/system.conf`; nocsd reads what needs no privileges (ADR 0027).
- The slew pad repeats its state every 0.25 s and the server stops the mount after
  1 s without a message, latching until the client lets go (ADR 0015).
- The WebSocket carries ~24 patches/s, **~19 kB/s per client (~70 MB an hour)**,
  88 % of it the raw INDI mirror that only `#/dev` shows (the Pi soak,
  [pi5-soak.md](../spikes/pi5-soak.md)); another session is reducing it. Whether
  that figure is before or after `permessage-deflate` (which uvicorn's `websockets`
  implementation offers and browsers accept) was not measured. Previews are JPEG,
  up to 1920 px wide, quality 85 (ADR 0012); their size on a real night was not
  recorded.
- Chilean mobile operators (and Starlink's IPv4) put customers behind carrier-grade
  NAT: a box on mobile data has no address the internet can reach, and neither has
  the owner's phone.

## Transport: the options compared

| | Mesh VPN: Tailscale (or Headscale) | Tunnel: Cloudflare Tunnel | Port forwarding + TLS | Plain WireGuard to a VPS |
|---|---|---|---|---|
| Behind CGNAT (box and phone) | Yes: both dial out; direct by NAT traversal, else through Tailscale's relays (DERP; nearest São Paulo) | Yes: the box dials out | **No**: needs a public address on the box's side (none on Chilean mobile data or Starlink IPv4) | Yes, through the VPS |
| Exposed to the internet | No: only devices in the owner's tailnet reach it | Yes, a public URL, unless Cloudflare Access is put in front | Yes: the port is scanned within hours | No |
| Who sees the traffic | Nobody: WireGuard end to end; the coordination server sees metadata (which devices, when), relays only ciphertext | **Cloudflare**: it terminates TLS and sees the passphrase, cookies, frames | Nobody | The VPS's owner (the user) |
| Cost | Free personal plan (non-commercial; 2026 terms list 6 users, unlimited personal devices); Headscale needs a server of one's own (a VPS, ~US$5/month) | Tunnel and Access free (up to 50 users), but **a domain on Cloudflare** (~US$10/year) per user | A dynamic DNS name; free certificates by ACME | A VPS (~US$5/month) |
| Accounts | A Tailscale account (Google, Apple, Microsoft, GitHub or email) | A Cloudflare account and a domain | Router access; a DNS name | A VPS provider |
| Setup from a phone | Install the Tailscale app, sign in; in NOCS tap *Turn on*, open the login link, approve | No app on the phone; but tunnel, DNS and Access are configured in Cloudflare's dashboard | Router settings, often impossible on a 4G router; certificates | Keys and configuration by hand on the VPS, a QR for the phone's WireGuard app |
| HTTPS (a secure context) | Yes: a Let's Encrypt certificate for `<box>.<tailnet>.ts.net`, renewed by `tailscale serve` | Yes, Cloudflare's | Yes, with ACME | Not by itself (an IP address) |
| Observers without an account | No (Tailscale's node sharing needs their own account) | Yes, a plain link | Yes | No |
| Work for NOCS | Small: run `tailscale up`/`serve`/`down` from nocs-system, read its status | Medium: the owner's Cloudflare setup is outside NOCS; a token on the box | Large, and the exposure needs a much stronger auth model | Large, and per-user infrastructure |

**Recommendation: Tailscale's client, with Tailscale's coordination server by default
and a Headscale server as an option** (the same client takes `--login-server`).
It is the only option that works with both ends behind CGNAT, opens nothing to the
internet, keeps the traffic end-to-end encrypted, and needs no domain, router or
server from the user. Its costs: the owner needs a Tailscale account and the app on
each phone, Tailscale learns which devices talk and when, and a relay adds latency
when the NAT on both sides defeats a direct path.

Cloudflare Tunnel stays a candidate for a later "observers over the internet" link
(a star party watching a session), not for control. Port forwarding is ruled out:
it does not work where the boxes are, and it would put a box that moves a mount on
the open internet behind one passphrase.

## Stages

| # | Stage | Contents | Check | Estimate | Status |
|---|---|---|---|---|---|
| R0 | Decisions | This plan; ADR 0037 | Review with the maintainer | 3–4 h | Proposed |
| R1 | Measure the weak link | A bench tool (`dev/bench/link.py`): bytes per client on the wire with and without `permessage-deflate` (raw socket counters), patches per second by subtree, preview sizes at 1920/q85, 1280/q75 and 960/q70 from the soak's simulated frames and from real night frames (`NOCS_TEST_FRAMES`); a run through a shaped link (`tc netem`: 150 ms ± 50 ms, 1 % loss, 1 Mbit/s); results in `docs/spikes/remote-link.md` | The numbers; nothing ships | 3–4 h | |
| R2 | Data saver | Per-client data saver (`?lean=1` on the WebSocket, on by itself for remote clients, a preference to change it): patches coalesced to at most one batch per second, no `indi.devices` unless the client asks (if the other session has not removed it already); a second, smaller preview per frame (1280 px, q75 unless R1 says otherwise) made by the same worker, `GET /api/previews/{id}?size=small`; downloads say their size first | Unit tests of the coalescing; API tests: a lean socket gets ≤ 1 batch/s and the same final state; the bench: under the budget | 6–8 h | |
| R3 | nocsd behind `tailscale serve` | nocsd reads `tailscale status --json` (no privileges) into a `remote` state; its own tailnet name joins the allowed host names (exactly that name, never `*.ts.net`); `X-Forwarded-*` trusted only from loopback, so cookies get `Secure` over HTTPS; requests classified as **remote** (from loopback through Tailscale's proxy, or from Tailscale's address ranges) or local; setup refused over remote; pairing throttled on its own counter for remote requests, so a remote attacker cannot lock out pairing at the rig; devices remember whether they were paired remotely | Unit tests (fake `tailscale` on the `PATH`, forged headers from a non-loopback peer ignored); API tests for each rule; the auth route walk extended to remote requests | 6–8 h | |
| R4 | Turning it on and off | nocs-system group `remote`: `remote.up` (start `tailscaled` if needed; `tailscale up` with the box's host name, routes, exit node, DNS and Tailscale SSH off, optional login server; `tailscale serve --bg --https=443 http://127.0.0.1:<port>`; returns the login link when one is needed), `remote.down` (`serve reset`, `down`: login kept), `remote.logout`; nocsd: `POST /api/system/remote` (on/off, login server), `DELETE /api/system/remote/login`; the login link only in that response, never in the state (whoever opens it first adds the box to their tailnet); refused while the box is in setup mode | Unit tests with a fake `tailscale`; nocs-system's tests (closed list, argument validation, no shell); API tests | 6–8 h | |
| R5 | Packaging and firewall | Image: Tailscale's signed apt repository and `tailscale`, `tailscaled` disabled until first turned on, `TS_NO_LOGS_NO_SUPPORT` if decided; `nocs-appliance`: `remote` in nocs-system's groups, firewall lets in 443 (and 80, if decided) on `tailscale0` and UDP 41641 for direct paths; PC: nothing installed, nocsd uses a Tailscale it finds (read only) | `packaging/deb/test.sh` and the image's smoke test: the unit is disabled, the firewall table loads with the new rules, nocs-system lists the group | 3–4 h | |
| R6 | Safety over a slow link | The WebSocket measures each client's round trip (application ping every 5 s, in its own state, not shared); the slew pad refuses to start when a client's recent round trip is over 500 ms or it is losing messages, and says to use Go to; local clients see that a remote device is connected (`clients.remote`, a count); turning remote access off from a remote device asks to confirm that it will cut this connection; Park, Stop and the sequence's Stop stay one tap everywhere | Unit tests; the pad with a delayed socket in tests; the bench through `netem` | 4–6 h | |
| R7 | Remote access in the app | Rig → *Remote access*: what it is and what it needs (the box on a network with internet, a Tailscale account, the app on the phone), *Turn on* → the login link, state (off, needs login, connecting, on with the address, expired, relay or direct), the address to copy, key expiry with a warning 14 days ahead, *Turn off*, *Log out*; Advanced: login server (Headscale); a *Remote* chip in the header when connected remotely, with the round trip; data saver in the preferences; en and es; `docs/ux.md`; `docs/user/` (a remote access page) | Browser against simulators and a fake `tailscale`, phone and wide, Night mode, both languages | 6–8 h | |
| R8 | Lab and field | Test Pi (agreed window): turn on from a phone, approve, open by `https://<box>.<tailnet>.ts.net` from mobile data; the box behind a phone hotspot or 4G router (CGNAT): direct or relay, round trip, bytes per hour, the pad's refusal on a bad link; key expiry and turning off; then the exit above in a field night | Test Pi; field test checklist item | 3–4 h + a night | |

Total **40–54 h**. Order: R0 → R1 → R3 → R4 → R5 → R2 → R6 → R7 → R8. R1 first because
its numbers set R2's budget; R2 can move earlier if the WebSocket reduction lands
first. R3–R5 are the minimum for a remote owner; R2 and R6 make it fit for mobile
data and safe; R7 makes it usable without a shell.

Data budget (proposed for R2, to confirm with R1): a data-saver client watching a
sequence under **10 MB an hour** for the state (≈ 3 kB/s) plus small previews of
**≤ 200 kB** each, so a 6-hour night with a frame every 5 minutes stays under
~100 MB on the phone's side and the same on the box's.

## Open decisions (with a recommendation each)

1. **Transport.** *Recommendation:* Tailscale's client and coordination server by
   default, Headscale as an advanced option (a login server URL); Cloudflare Tunnel
   only later, for observers. **Needs the maintainer:** a Tailscale account to build
   and test it (free; R4 onwards, and R8 on a test Pi), and acceptance that every
   NOCS owner who wants remote access needs one too, or a Headscale server.
2. **HTTPS.** *Recommendation:* `tailscale serve` terminates TLS with the tailnet's
   Let's Encrypt certificate for `<box>.<tailnet>.ts.net` and proxies to nocsd on
   loopback; Tailscale renews it. It needs MagicDNS and HTTPS certificates switched
   on once in Tailscale's admin console (NOCS detects and explains it), and the name
   appears in public certificate transparency logs (the tailnet's random name, not
   the owner's). Bonus: over that name the app is a secure context, so geolocation,
   wake lock and offline installation work, also at home with Tailscale on.
3. **Plain HTTP over the tailnet as well?** *Recommendation:* yes, keep port 80 open
   on `tailscale0` as a fallback while HTTPS certificates are off in the tailnet:
   WireGuard already encrypts it, the address is an IP so the host check passes, and
   only the secure-context features are lost. The alternative (443 only) is stricter
   but leaves an owner who skipped the admin-console step with nothing.
4. **Pairing over remote access.** *Recommendation:* allowed (a phone paired at
   `nocs.local` needs a new pairing for the tailnet name anyway), with its own
   throttle counter and the same backoff; setup mode never over remote; devices
   paired remotely marked so in the device list. Only devices in the owner's tailnet
   can try at all.
5. **Observers over remote access.** *Recommendation:* no, not in this plan: the
   observer switch keeps applying to local clients only, and remote observers come
   with a separate decision (Tailscale node sharing, or a read-only tunnel).
6. **What a remote owner may do.** *Recommendation:* everything a local owner can:
   parking on clouds or starting tomorrow's sequence is the point. Extra care where
   the link matters: the slew pad refuses on a slow or lossy link (R6; the 1 s dead
   man's switch already stops the mount when messages stop), people at the rig see
   that a remote device is connected, and turning remote access off from remote asks
   first. No extra confirmation on Go to or power outputs: they already confirm
   where it matters, and a remote owner cannot do anything a thief of a paired phone
   could not.
7. **Tailscale's log upload.** Tailscale's client uploads connection logs to
   `log.tailscale.com` unless `TS_NO_LOGS_NO_SUPPORT=true`, which also forfeits
   Tailscale's support. *Recommendation:* turn the upload off in the image (privacy;
   NOCS supports its users, Tailscale's support is not part of the product).
8. **Key expiry.** Tailscale expires a device's key after 180 days by default, which
   would drop a box left at a site. *Recommendation:* NOCS shows the expiry and warns
   14 days ahead, and the instructions ask the owner to disable expiry for the box in
   the admin console; NOCS does not try to do it (it would need an API key).
9. **Data saver.** *Recommendation:* on by itself for remote clients, off on the LAN,
   switchable in the preferences; budget as above, set from R1's numbers.
10. **Packaging.** *Recommendation:* Tailscale in the Pi image, from Tailscale's
    signed apt repository (a third-party repository with root's trust, like the INDI
    and PHD2 PPAs), `tailscaled` disabled until the owner first turns remote access
    on (~30 MB); `nocs-appliance` adds the firewall rules and the `remote` group; no
    separate NOCS package. On a PC nocsd only reads a Tailscale its owner installed:
    the tailnet name is allowed and `tailscale serve` works, but turning it on and off
    is the owner's business (the `remote` group stays off, as the network one does).
    The alternative, an optional `nocs-remote` package installed from the app, adds a
    package and an install step for ~30 MB.
11. **The box's own internet at a site.** *Recommendation:* a 4G Wi-Fi router (or a
    phone's hotspot) that the box joins as a known network; USB modems
    (ModemManager) later. While remote access is on and no phone is on its access
    point, the fallback retries known networks every minute instead of five, so a
    router that drops for a while gets the box back sooner.

## Not in this plan

- Observers over the internet (a read-only link for a star party).
- USB 4G modems and SIM management.
- Push notifications to the phone when a sequence fails (needs a push service).
- Tailscale's Funnel (publishing the box to the internet): never turned on; NOCS
  replaces any serve configuration with its own.
- HTTPS on the LAN without Tailscale (a local CA; phase 6's deferred item).

## Notes

- Shared files kept small: `api/auth.py` (remote classification, second throttle),
  `api/schemas.py` (`remote` state and requests), generated types, `api/app.py`
  wiring, `nocs.system.operations` (the group), the firewall and the Rig screen.
- To check in R3 against a real `tailscale serve`: that it passes the original
  `Host` and sets `X-Forwarded-For` / `X-Forwarded-Proto` and `Tailscale-User-*`
  headers as documented, and that the WebSocket upgrade crosses it.
