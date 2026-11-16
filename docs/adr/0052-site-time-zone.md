# 0052. A site has a time zone, worked out from its position, and the app shows its times in it

Date: 2026-11-16 · Status: Proposed · Amends: [ADR 0038](0038-saved-sites.md) (what a site holds), [ADR 0015](0015-mount-control-and-client-time.md) (the mount's UTC offset)

## Context

The app formatted every time in the browser's time zone, and the mount got its UTC
offset from the client that reported the clock. The maintainer wants every time in
the observing site's zone ("Experiencia NOCS"): a rig run from another city, or a
phone that kept its home zone, showed the night's times shifted. Facts:

- **A site is a position** (ADR 0038); its time zone follows from it, but not by a
  formula: zones follow borders, and summer time follows the zone's rules.
- **The box is offline in the field**: the zone must come from data on the box.
  `tzfpy` maps a position to its IANA zone from a bundled map (3 MB, wheels for arm64
  and amd64, no dependencies); `timezonefinder` does the same with numpy, cffi and a
  larger dataset. Python's `zoneinfo` (the system's tz database) gives a zone's
  offset at any date.
- **Browsers format in any IANA zone** (`Intl.DateTimeFormat`'s `timeZone`).

## Decision

- **A site may name its zone** (`timezone`, an IANA name, validated against the map's
  zones, the nautical `Etc/GMT±N` ones and the system's); without one it is the zone
  at its position (at sea, the nautical zone), worked out again when it moves. The
  state shows each saved site's zone in effect (`sites.saved.<id>.zone`); the site
  editor offers the names from `GET /api/sites/zones` and leaves it empty by default.
- **The app shows every time in the active site's zone**, else the browser's. The
  shell keeps the zone for the formatting helpers and draws the screens again when
  it changes (which is when the active site does).
- **The mount gets its UTC offset from the active site's zone** at that moment
  (summer time included), else from the client's report as before.

## Consequences

- One more dependency (`tzfpy`) in nocsd.
- Changing the active site redraws the screen, closing an editor that was open: the
  site changes rarely, and from Rig.
- A site saved before this has no `timezone` and gets its position's; nothing to
  migrate.
- A zone the browser does not know falls back to the browser's own.
