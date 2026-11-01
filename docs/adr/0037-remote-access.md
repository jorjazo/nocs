# 0037. Remote access over the owner's Tailscale tailnet

Date: 2026-11-01 · Status: Proposed

## Context

Owners want to reach their box from outside its network: the rig in the garden while
they sit inside on another network, or at a dark site while they are in the city.
ADR 0014 built authentication with that in mind and left HTTPS for it; ADR 0028 left
the appliance closed to everything but port 80 on its own networks. Facts that shape
the decision:

- Boxes at rural Chilean sites reach the internet by mobile data, usually through a
  4G router, and the owner's phone is on mobile data too. Chilean operators, and
  Starlink's IPv4, put both behind carrier-grade NAT: neither has an address the
  internet can reach. Port forwarding cannot work there.
- The box moves a mount, heats dew straps and switches power. A box published on
  the internet would face scans and passphrase guessing with only the global
  throttle of ADR 0014 between them and the hardware.
- Mesh VPNs (Tailscale; Headscale, an open-source server for the same client) put
  each device on a private network by dialling out from both ends, with WireGuard
  end to end, NAT traversal, and relays when no direct path exists. Tailscale's
  personal plan is free for non-commercial use; it needs an account and its app on
  each phone. Its client can serve HTTPS with a Let's Encrypt certificate for the
  device's name in the tailnet (`<box>.<tailnet>.ts.net`), renewing it itself
  (`tailscale serve`). Its daemon's status is readable without privileges; changing
  it needs root (or an operator user).
- Tunnels (Cloudflare Tunnel) also dial out and give HTTPS, but terminate TLS at the
  provider, which then sees passphrases, cookies and frames; publish a public URL;
  and need a domain on the provider per user.
- The WebSocket sends ~19 kB/s per client on the soak's simulated night, mostly the
  raw INDI mirror; previews are JPEG up to 1920 px at quality 85 (ADR 0012). Mobile
  data costs per gigabyte at both ends.
- The slew pad stops the mount after 1 s without a message from the client
  (ADR 0015), so a dropping link stops it; jitter of a few hundred milliseconds
  stops it too.

## Decision

### Transport

- **Remote access is the owner's Tailscale tailnet.** The box runs `tailscaled` and
  joins the owner's tailnet when the owner turns remote access on; phones reach it
  only from inside that tailnet. Nothing on the box is opened to the internet.
- Tailscale's coordination server by default; a **Headscale** server as an option,
  given as a login server URL.
- The box advertises no routes and is no exit node; it accepts no routes or DNS from
  the tailnet; Tailscale SSH and Funnel stay off, and NOCS replaces any serve
  configuration with its own.
- Tailscale's client log upload is turned off (`TS_NO_LOGS_NO_SUPPORT`).

### HTTPS and nocsd

- `tailscale serve` terminates HTTPS on 443 of the box's tailnet address with the
  tailnet's certificate and proxies to nocsd on loopback. Plain HTTP to the tailnet
  address on nocsd's port stays possible as a fallback (WireGuard encrypts it; it is
  not a secure context).
- nocsd reads `tailscale status --json` and allows **its own tailnet name** in the
  host name check (exactly that name; public DNS cannot answer for it with another
  address, and an attacker cannot get a certificate for it). `*.ts.net` as a whole
  is never allowed.
- `X-Forwarded-*` headers are trusted only from loopback, so the cookie is `Secure`
  over HTTPS and a client on the network cannot pretend to come through the proxy.
- A request is **remote** when it comes from loopback through Tailscale's proxy or
  from Tailscale's address ranges (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`) on the
  tailnet interface; otherwise local.

### Authentication over remote access (amends ADR 0014's enforcement)

- Pairing works over remote access, with a **throttle of its own** (same backoff),
  so failures from outside cannot lock pairing at the rig; a device paired remotely
  is marked so in the device list.
- Setup mode is never available over remote access.
- Observer access applies to local clients only; remote clients must be paired.
- The login link Tailscale gives to add the box to a tailnet goes only to the owner
  who asked, in the reply; it never enters the state (whoever opens it first owns
  the box's place in a tailnet).

### Turning it on and off

- nocs-system gets a `remote` group (ADR 0027): `remote.up` (start `tailscaled`,
  `tailscale up` with the settings above, set up `serve`; returns a login link when
  one is needed), `remote.down` (keeps the login) and `remote.logout`. The appliance
  enables the group; a PC does not, and there nocsd only reads a Tailscale its owner
  runs.
- On the Pi image `tailscaled` is installed from Tailscale's signed apt repository
  and stays disabled until the owner first turns remote access on.
- The appliance's firewall lets in, on `tailscale0` only, HTTPS (443), nocsd's port,
  and WireGuard's UDP port for direct paths.

### Weak links and safety

- Clients connected remotely get a **data saver** by default (switchable): state
  patches coalesced to at most one batch per second, no raw INDI mirror, a smaller
  second preview per frame. Its budget is set from measurements (plan, stage R1).
- The WebSocket measures each client's round trip; the slew pad refuses to start on
  a slow or lossy link and points to Go to. The dead man's switch is unchanged.
- A remote owner can do everything a local owner can. Local clients see that a
  remote device is connected.
- NOCS shows the box's Tailscale key expiry and warns before it; disabling expiry is
  left to the owner in Tailscale's admin console.

## Consequences

- Works where the boxes are (CGNAT on mobile data at both ends) without a domain, a
  server or router access, and without exposing the box: only the owner's tailnet
  can reach it, and pairing still stands behind that.
- Each owner who wants remote access needs a Tailscale account (or a Headscale
  server) and the Tailscale app on their phones. Tailscale learns which devices talk
  and when, not what they say. Relayed paths add latency.
- Over the tailnet name the app is a secure context: geolocation, wake lock and
  offline installation work there, which the LAN still lacks.
- The tailnet name appears in public certificate transparency logs.
- A third-party apt repository joins the image, trusted as root like the INDI and
  PHD2 PPAs.
- A pairing still belongs to a host name: a phone paired at `nocs.local` pairs again
  for the tailnet name.
- Remote observers (a star party watching a session) need a later decision.
