# 0047. Observers do not see where the box is, or which networks it knows

Date: 2026-11-14 · Status: Proposed · Amends: [ADR 0014](0014-authentication-and-pairing.md) (what observers get)

## Context

ADR 0014 gives observers the whole state, and left the site's coordinates in it as
the owner's choice: observer access is off by default. Since
[ADR 0046](0046-no-host-name-check.md) removed the host name check, turning it on
also shares that view with any page the owner opens, rebound to the box's address.
The state then tells such a page where the owner observes (often home) and which
networks the box knows:

- `mount.site`, every saved site in `sites`, the GPS fix in `gps`;
- `GEOGRAPHIC_COORD` of the mount, of a GPS driver or a weather driver in the INDI
  mirror, and the drivers' messages: INDI's telescope base class logs every new
  site with its latitude and longitude;
- `network.ssid`, `known`, `joining` and `last_join`: Wi-Fi names, which public
  databases map to places;
- `GET /api/sky/tonight`, open to observers, returns the active site.

## Decision

- Observers get a redacted state; the owner keeps the whole one. One list of rules
  (`nocs.api.observers.RULES`) is applied to the snapshot of `GET /api/state`, and
  to the WebSocket's snapshots and patches, history replays included:
  - `sites` is left out;
  - `mount.site`, the GPS's `latitude`, `longitude`, `elevation` and `site`,
    `network.ssid`, `joining` and `last_join` are `null`, and `network.known` empty,
    so the state still matches its schema;
  - `GEOGRAPHIC_COORD` is left out of every INDI device, and INDI messages that
    speak of a latitude, longitude, location, site, elevation or GPS are dropped.
- A patch keeps its version for observers: changes inside a hidden node are dropped
  (a patch may arrive empty), changes of a hidden node become its replacement, and
  changes above one are redacted like a snapshot. Applying them to an observer's
  snapshot gives what a new snapshot would.
- The almanac's `site` is `null` for observers.
- What follows from what is left stays: the mount's altitude and azimuth with its
  coordinates and the time, and tonight's sky (twilights, targets' altitudes), give
  the site to whoever computes it. Observers watch the session through them; hiding
  them would leave little to watch.

## Consequences

- A page that sweeps private addresses for open APIs, rebound to a box with observer
  access on, gets no coordinates or Wi-Fi names to read. An attack written for NOCS can
  still compute the site from the mount and the sky: observer access stays off by
  default, and the owner should turn it on only while it is in use.
- The box's own access point name (`network.ap_ssid`) stays: it is on the air anyway.
- Observers' screens show no site (Polar's, the mount sheet's) and cannot tell when
  the site changes; Tonight's almanac is asked again every few minutes anyway.
- A new state field with a location or a network name needs a rule; the rule list is
  the one place that says what observers do not see.
