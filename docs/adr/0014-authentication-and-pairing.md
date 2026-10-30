# 0014. Authentication and device pairing

Date: 2026-10-30 · Status: Accepted · Amended: 2026-10-30 (host names, see below)

## Context

NOCS commands move a mount, heat dew straps and switch power outputs: nobody on
the network should be able to send them by accident or on purpose. The design
(§10) asks for a first-run owner passphrase, devices paired once with a
long-lived token that can be listed and revoked, and an optional read-only
observer. Local use must stay frictionless, and remote access is a long-term goal.

Constraints:

- nocsd is a single process serving one owner. No user accounts, no email, no
  recovery flows that need the internet.
- Browsers cannot put headers on a WebSocket handshake: whatever authenticates
  the state channel must travel as a cookie.
- Until phase 6 nocsd serves **plain HTTP** at `nocs.local` or an IP address.
  Browsers only offer some APIs in a *secure context* (HTTPS, or `localhost`):
  - **Geolocation**: unavailable. The site's location must be typed in (or come
    from a saved site, later from a GPS); the client's clock is available, so time
    can still come from the phone.
  - **Service workers**: unavailable, so the PWA cannot be installed with offline
    support (ADR 0004); at most a home-screen shortcut that needs the server.
  - **Screen Wake Lock**: unavailable; the phone may sleep during a session. The
    server never depends on a client being awake (never lose a night).
  - Also secure-only, so the web app must not rely on them: Notifications, the
    async Clipboard API, `crypto.subtle` and `crypto.randomUUID()`.
  - Cookies cannot be `Secure`, and the passphrase and token cross the network in
    clear. On the NOCS access point the Wi-Fi password protects them; on a home
    network, anyone on that network who sniffs traffic could take them.
  - Development on `localhost` *is* a secure context and hides all of this: check
    on a phone through the Pi's address.
- HTTPS on a LAN appliance (local CA, per-device domain with ACME, certificate
  pinning) is a project of its own and belongs with remote access in phase 6.

## Decision

### Owner passphrase and setup mode

- Authentication data lives in `auth.json` in the config directory
  (`~/.config/nocs/`, mode 0600, written to a new file and renamed into place).
- While it holds no passphrase the server is in **setup mode**: the only thing a
  client can do is create the passphrase (`POST /api/auth/setup`), which also
  pairs that client. Everything else that needs a role is refused. Whoever reaches
  the server first claims it; the NOCS access point is already password-protected,
  and a home network is the owner's own.
- The passphrase (at least 8 characters, NFC-normalized, no composition rules) is
  stored with `hashlib.scrypt` (stdlib): random 16-byte salt, `n=2^16, r=8, p=1`
  (64 MiB, 0.22 s on the Pi 5, measured), parameters stored next to the hash so
  they can be raised later. Hashing runs in a worker thread, one at a time.
- Wrong passphrases are throttled globally (one owner, so per-address limits only
  help an attacker who can change address): after 5 consecutive failures, every
  attempt waits for a delay that doubles up to 60 s (`429` with `Retry-After`);
  a success resets it. Paired devices keep working during a lockout.
- Changing the passphrase (`PUT /api/auth/passphrase`) needs a paired device *and*
  the current passphrase. Paired devices stay paired: revoking them is a separate,
  explicit action.
- A forgotten passphrase is recovered by whoever has a shell on the box: deleting
  `auth.json` and restarting nocsd returns to setup mode and unpairs every device. A friendlier reset
  (a button on the box, nocs-system) can come in phase 6.

### Device pairing

- `POST /api/auth/pair` with the passphrase and a device name (chosen by the
  client, e.g. "Pixel 8") creates a device: an id, the name, creation and last-use
  times, and a token of 32 random bytes (`secrets`). The server keeps only the
  token's SHA-256: it is a random secret, not a password, so a fast hash is enough
  and lets every request find its device in a dictionary.
- The token is sent only as a cookie, `nocs_device`: `HttpOnly`,
  `SameSite=Strict`, `Path=/`, and `Secure` when the request came over HTTPS.
  It never appears in a response body, so scripts on the page cannot read it.
  Browsers cap cookie lifetime at 400 days, so `GET /api/auth` (which the app calls
  on start) renews it: a device used at least once a year stays paired.
- Devices are listed with `GET /api/auth/devices` and revoked with
  `DELETE /api/auth/devices/{id}`; revoking the current device also clears its
  cookie (that is "log out"). Last-use times are kept in memory and written at
  most once an hour.
- Non-browser clients use the same cookie (`curl -c/-b`, httpx cookie jars).

### Roles

| Role | Who | Can |
|---|---|---|
| owner | a request with a valid device cookie | everything |
| observer | anyone else, **only while observer access is on** | `GET /api/state`, the WebSocket, `GET /api/previews/*` |
| anonymous | anyone else | `GET /api/health`, `GET /api/auth`, setup and pairing, the web app's static files |

- Observer access is **off by default** and switched by the owner
  (`PUT /api/auth/observer`). The state tree will hold things like the site's
  coordinates; showing them to everyone on a shared network (a star party) must
  be the owner's choice.
- Observers get what the screens need to *watch* a session, not the owner's
  configuration (profiles, driver catalog, serial ports) or data (frame downloads,
  catalog from ADR 0013). Anything in the state tree is visible to observers, so
  nothing secret may be put there: the device list lives only behind REST.
- `GET /api/auth` tells a client where it stands: whether setup is required, its
  role, its own device, and whether observer access is on.

### Enforcement

- One ASGI middleware decides access for every request **before routing**, from a
  short table of public and observer endpoints (method and path). **Everything
  else under `/api` requires the owner**, so an endpoint added later is protected
  even if its author forgets about authentication. A test walks all registered
  routes and checks that each one outside the table refuses anonymous requests.
  Refusals are `421` (unknown host name), `401` (no valid device) or `403` (bad
  origin); a refused WebSocket handshake is closed before it is accepted.
- The middleware stores the request's role and device in the ASGI scope, where
  endpoints that need them (`/api/auth`, revoking the current device) read them.
- A WebSocket keeps the role it had at the handshake. When its device is revoked,
  or observer access is switched off, the server closes it with code 4401; the
  client then asks `GET /api/auth` and shows pairing.
- **Host name check (DNS rebinding)**, *added 2026-10-30*: every HTTP request
  and WebSocket handshake, public ones and the web app's static files included,
  must name the server by an IP address (v4 or v6, with or without a port),
  `localhost`, an mDNS name ending in `.local`, or a name listed in
  `NOCS_HOSTNAMES` (comma-separated; e.g. a router's `nocs.lan`). Anything
  else, or no `Host` at all, gets `421` with a message naming the setting.
  Without it, a page on an attacker's domain whose DNS is rebound to the box's
  address is same-origin with itself: it would pass the Origin check, could
  claim a box in setup mode or pair with a phished passphrase, and its cookie
  would be stored under the attacker's name. Public DNS cannot answer for IP
  literals or `.local` names, so those cannot be rebound from the internet.
- **Origin check (CSRF and cross-site WebSocket hijacking):** every request with
  an unsafe method (`POST`, `PUT`, `PATCH`, `DELETE`) and every WebSocket
  handshake that carries an `Origin` header must come from the server's own
  origin (the `Origin` host and port equal the `Host` header); `Origin: null` is
  refused. Requests without `Origin` come from non-browser clients, which hold no
  ambient cookies, and are allowed. `SameSite=Strict` already keeps the cookie off
  cross-site requests; the Origin check covers what it does not: other origins of
  the same site, and observers' WebSockets, which carry no cookie at all. The Vite
  dev server proxies without rewriting `Host`, so it passes as same-origin.
- Previews switch from `Cache-Control: public` to `private`: no shared cache may
  keep them.

## Consequences

- One passphrase and one cookie per device: no login screen after pairing, which
  keeps local use frictionless, and a lost phone is one revocation away.
- New endpoints are owner-only unless someone deliberately adds them to the
  table, which a reviewer can see in one place.
- Until HTTPS (phase 6), credentials are only as safe as the Wi-Fi they cross,
  and the web app must live without geolocation, offline installation and wake
  lock: location is entered by hand, and the UI should suggest disabling the
  phone's auto-lock during a session.
- A pairing belongs to the host name the browser used: the cookie of
  `nocs.local` is not sent to the Pi's IP address, nor to a new name if the box is
  renamed (or if mDNS renames it to `nocs-2.local` after a name clash). Each name
  needs its own pairing. Several NOCS boxes on one network each keep their own
  cookie as long as their names differ, which they need anyway (design §11).
- DNS rebinding is closed by the host name check, without HTTPS (this replaces
  the original consequence, which left it open for observers until phase 6 and
  missed that a rebound page could claim a box in setup mode). The cost: a box
  reached by any other name (a router's DNS name, a reverse proxy) needs that
  name in `NOCS_HOSTNAMES`.
- Tests of the API pair their client first; a helper does it.

## Amendments

- 2026-10-30: host name check added to the enforcement, after a review found
  that a page using DNS rebinding passed the Origin check and could set the
  passphrase of a box in setup mode, then command it. Amended in place rather
  than superseded: the ADR had just been accepted and nothing else changes.
