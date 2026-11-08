# 0038. Sites belong to the box: a list of saved sites and one active site

Date: 2026-11-08 · Status: Proposed · Supersedes in part: [ADR 0011](0011-equipment-profiles-and-driver-management.md) (the profile's site), [ADR 0029](0029-system-time-and-site.md) (site from a GPS)

## Context

ADR 0011 put the site in the equipment profile, next to the optics, without
weighing it ("the profile also holds the imaging and guiding optics and the site").
ADR 0029 then had a GPS offer its position for the active profile. Facts that shape
the change:

- A site is where the rig stands, not what it is made of. The maintainer's portable
  rig (AM5) goes to several places, and two rigs set up in the same backyard repeat
  its coordinates and its horizon, which takes a while to measure.
- One NOCS box runs one rig at a time, at one place: there is never more than one
  site in use at once.
- What reads the site today goes through the active profile (`Profile.site`): the
  night's almanac and targets' visibility (`sky/`), sky flats (`calibration/`), the
  mount's site and its check (`mount/`), polar alignment (`align/`), sequences'
  schedules (`sequence/`), the FITS headers (`SITENAME`, `SITELAT`, `SITELONG`,
  `SITEELEV`) and the catalog's nights (`storage/`).
- A GPS fix wanders by metres, and a site typed in by hand or picked on a map is
  rarely more precise than a few hundred metres: neither the night nor the pointing
  changes noticeably within 500 m.
- Backward compatibility does not matter before v1.0.0: profiles may simply lose
  their site.

## Decision

- **NOCS keeps a list of saved sites**, apart from profiles, in the configuration
  directory: `sites.json` holds the sites and which one is active. A site has an id
  NOCS generates (so a rename keeps every reference), a name, latitude, longitude,
  elevation and its horizon (the model `Profile.site` has today).
- **The box has one active site**, or none, chosen by the owner. Profiles no longer
  hold a site. The state publishes the saved sites and the active one (`sites`);
  sites are not secrets, so observers see them.
- **Everything that needs the site reads the active one**: the sky, flats, the
  mount, polar alignment, sequences, FITS headers and the catalog (which records the
  active site's name for a night, as it records the profile's today). Without an
  active site they behave as they do today with a profile that has none.
- **The mount's site follows the active site** (ADR 0015): NOCS sends it when the
  mount becomes ready and when the active site changes or is edited.
- **The active site cannot change while a job holds the mount** (a go to, a
  sequence, polar alignment, sky flats, centring), nor can the active site be edited
  or deleted then: a schedule, a pointing or a polar axis computed from one site
  would be wrong for another. Exposures and previews do not hold it back. Other
  sites can be added, edited and deleted at any time. Deleting the active site
  leaves the box with none.
- **Site from a GPS** (replaces ADR 0029's): with a 3D fix, NOCS looks for the
  saved site nearest to it within **500 m** on the ground (elevation does not
  count).
  - When that is the active site, nothing is offered.
  - When it is another saved site, the app offers to make it active.
  - When there is none, the app offers to save the GPS's position as a new site
    (with its elevation) and make it active.

  A site is still never changed without the owner asking. The client's geolocation,
  once the app is served over HTTPS (ADR 0028), will go through the same matching.
- **The app** lists the saved sites in Rig, the active one marked and the others
  ready to use, and edits each one on its own page (name and position, filled from
  the GPS; the horizon is kept as it is, as the profile editor kept it). Tonight
  leads there when there is no active site. The profile editor loses its site.

## Consequences

- A rig moves between saved places by choosing one, and a new place costs one tap
  with a GPS; a horizon is measured once per place.
- Changing profiles in the same place no longer changes the site, and a profile
  connected somewhere new no longer carries an old site along.
- Existing profiles lose their site: after upgrading, the owner enters the sites
  again (no migration before v1.0.0).
- With one active site per box, a box serving two rigs at two places at once is not
  possible; that is not something one box does.
- Profiles exported to another box no longer carry a site; exporting sites is left
  for later.
