# 0042. A new site from the mount or the GPS, and a site step in the first run

Date: 2026-11-12 · Status: Proposed · Amends: [ADR 0038](0038-saved-sites.md) (where a new site comes from), [ADR 0041](0041-preparation-steps-run-when-they-can.md) (no site step in the first run)

## Context

On rc4's field night (2026-11-11, [field notes](../roadmap/v0.1/rc4-field-notes.md),
22:48) the maintainer asked that a new site take its coordinates from the mount, from
the GPS, later from the phone and perhaps from Google Maps. Since ADR 0041, polar
alignment needs the box's active site and Tonight's checklist blocks on its absence,
so a box without one cannot get far into a night; ADR 0041 left a site step out of the
first run until a site could come from somewhere other than typed coordinates.
Facts that shape the decision:

- The mount state already publishes the mount's own site (`mount.site`, its driver's
  `GEOGRAPHIC_COORD` read through the `Mount` facade) and how it compares with the
  active site (`site_check`). The GPS state (`gps`, gpsd's fix, ADR 0029) already
  publishes the position and the saved site within 500 m of a 3D fix.
- NOCS sends the active site to the mount whenever it becomes ready (ADR 0015, 0038):
  with an active site, the mount's site is that one again. The mount's own site is
  news only where something else set it: its hand controller or app (the AM5's), a
  GPS built into the mount, or the box having no active site yet.
- A driver that never got a site reports 0°, 0°; the telescope simulator reports the
  last one it was given.
- An INDI GPS driver is not a role in profiles; the GPS NOCS reads is gpsd's (ADR 0029).
- The first run asks for USB devices to be unplugged (USB 3 drowns 2.4 GHz Wi-Fi, rc4
  field notes, 22:48), and no profile is connected then: the mount and the GPS are
  usually absent. The phone's location needs HTTPS (ADR 0028), which the box does not
  serve yet.
- Polar alignment and the night need the site only roughly (rc4 field notes, 22:48):
  a few kilometres off change nothing measurable, so a town's coordinates from a map
  are enough.

## Decision

- **The site editor offers each source of a position as a button**: *From the mount*
  (the connected mount's own site) and *From the GPS* (gpsd's fix; 2D gives latitude
  and longitude, 3D the elevation too). A button fills the fields, which stay editable
  until the site is saved. A source with nothing to give is disabled and says why: no
  mount connected, a mount without a site or with 0°, 0°, no GPS, no fix. When the
  position is within 500 m of a saved site (another one than the site being edited)
  the editor says so, naming it (the active site, say), but does not stop the owner.
- **No new endpoint**: the app reads both positions from the state it already has,
  and saves the site through the sites API as a typed one.
- **The first run gets an optional Site step**, after the box's name and before the
  review: a saved site (the active one by default, when the box has some already) or
  a new one typed in, filled from the mount or the GPS only when one of them happens
  to have a position; or none for now. It says that a rough position is enough. As
  with the rest of the setup, nothing is saved before the last step: applying saves
  the site and makes it active first, then sets up the network (which may drop the
  phone); a retry after a failure edits the site it saved instead of adding another.
- **Later, not now**: the phone's location, once the app is served over HTTPS
  (ADR 0028), through the same matching as a GPS fix (ADR 0038); and a position from
  Google Maps, which needs a choice first between a pasted link (parsed on the box,
  no terms to accept, works offline once copied) and an embedded map (internet in
  the field, an API key, and Google's terms of use).

## Consequences

- A rig whose mount knows where it is (from its own app or GPS) gets a site with one
  tap; a box with a USB GPS too, as before.
- A first run that fills the Site step leaves the box ready for the checklist's polar
  alignment; one that skips it gets the checklist's link to add a site, as before.
- With an active site, *From the mount* mostly gives that site back; the editor says
  so rather than hiding the button.
- The 0°, 0° rule would refuse a real site in the Gulf of Guinea.
