# 0044. A renamed box hands the pairing over to its new name

Date: 2026-11-12 · Status: Proposed · Amends: [ADR 0014](0014-authentication-and-pairing.md) ("a pairing belongs to the host name the browser used", one cookie per device), [ADR 0042](0042-site-from-the-mount-and-first-run.md) (the first run's name step)

## Context

A pairing is a cookie, and a browser keeps cookies per host name (ADR 0014). When the
owner renames the box (Rig → This computer → Rename, or the first run's name step),
`nocs.local` stops answering as soon as avahi announces the new name, and the browser
at `http://nocs-lab.local` has no cookie: the box asks for the passphrase again. The
maintainer met it on the lab Pi; until now the app only said so.

- The browser that renamed the box is paired and is the owner: nothing about the new
  name is less trusted than the old one; only the cookie is missing.
- The page cannot set a cookie for another host name, nor read the old one (it is
  `HttpOnly`). Something has to travel from the old origin to the new one in the
  browser itself: a URL.
- A URL's query reaches the server's access log and the next page's `Referer`; its
  fragment (`#…`) is never sent by the browser.
- Once renamed, the old name may stop resolving before a second request goes out; in
  the first run the access point also restarts, and the phone drops off it.
- A page reached by an address (`10.42.0.1`, `192.168.1.40`) or another name
  (`NOCS_HOSTNAMES`) keeps working after a rename: only `<old name>.local` breaks.

## Decision

- **Handoff tokens.** `POST /api/auth/handoff` (owner only, like everything not
  listed) returns a one-time token, 32 random bytes (`secrets.token_urlsafe`), valid
  for **2 minutes**, bound to the device that asked. nocsd keeps only its SHA-256, in
  memory: never in `auth.json`, the state or a log. At most 4 are outstanding; a
  fifth replaces the oldest.
- **Redeeming.** `POST /api/auth/handoff/redeem {token}` is public, and goes through
  the host name and Origin checks like everything else. A valid token is used up and
  pairs the browser **as the same device**, under the host name it used, with a new
  cookie; `last_used` is updated. A wrong, expired or used token is `403`, counted
  like a wrong passphrase (5 free, then a doubling wait up to a minute: `429` with
  `Retry-After`), with a count of its own so that it does not hold up pairing.
- **A device holds several cookies.** `auth.json` keeps `tokens_sha256` (a list)
  instead of one `token_sha256`: the old name's cookie, the address's, the new
  name's. At most 8; a new one beyond that replaces the oldest. Revoking a device
  ends all of them and its pending handoffs. No migration (nothing is compatible
  before v1.0): an `auth.json` of an earlier version fails to load; remove it and
  pair again.
- **The web app gets the token before renaming**, and only when the page was reached
  by the box's current `<name>.local`: then the rename (or the first run's apply)
  goes ahead. Renaming from an address or another name gets no token and says that
  other devices pair again.
- **It waits for the new name, then goes there.** It tries
  `http://<new>.local[:port]/api/health` (`no-cors`: an opaque answer is enough)
  every 2 s for up to 60 s, showing how long it has waited, then opens
  `http://<new>.local[:port]/#/<route>?handoff=<token>`: the token in the fragment,
  after the route, which the router ignores. If the name does not answer in time, a
  link opens it by hand and a button waits again. In the first run, whose last
  screen has instructions to read (join the access point again, or switch networks),
  a button starts the wait instead.
- **The new page** takes the token out of the fragment (`history.replaceState`)
  before anything else, redeems it, then asks `GET /api/auth` as usual. If redeeming
  fails, pairing shows with a line saying why.

## Consequences

- Renaming the box from its `.local` name keeps that browser paired: one device in
  the list, not two. Other browsers that used the old name still pair again; so does
  this one if it reaches the new name more than two minutes after the rename (a phone
  that must join the access point again may take that long).
- A token in a URL can leak through the screen, the browser's history or a shared
  link. It is useless after one use or two minutes, the history entry loses it at
  once, and a guess is throttled; 32 random bytes are not guessed anyway.
- If avahi has to rename the box again after a clash (`nocs-lab-2.local`), the page
  waits for a name that is not the box's, or reaches another device that answers it;
  the token, taken there, is only good at this box, within two minutes.
- Browsers may cache a failed lookup of the new name for a while: the wait starts only
  after the rename, never before.
- The same mechanism could later move a pairing between `nocs.local` and `10.42.0.1`
  (ADR 0028: a phone at home and in the field needs two pairings): the page at one
  name would hand over to the other. Not done here.
