# 0041. Tonight's checklist offers a step only when it can run; the server says what blocks it

Date: 2026-11-12 · Status: Proposed · Amends: [ADR 0034](0034-polar-alignment.md) (the site polar alignment uses), [ADR 0038](0038-saved-sites.md) (what reads the active site)

## Context

Tonight's checklist (connect, polar align, focus, frame the target, guide; stage 3.6)
gives the first step not done the one primary button. On rc4's field night it
offered polar alignment right after Connect while the box had no active site, so
the step failed when started: a checklist that offers what cannot run is not a
workflow ([rc4 field notes](../roadmap/v0.1/rc4-field-notes.md), 22:55). Facts:

- What a step needs was known in two places that disagreed. The server refused a
  polar alignment without "the site" (`align/service.py` `plan`), which was the box's
  active site **or else the mount's own** (`MountService.site`); the polar screen
  checked the mount's reported site; the checklist checked only that a mount and a
  main camera were ready.
- A mount's own site is whatever its driver holds: the handset's, a previous
  client's, or a default. NOCS cannot tell a real one from a default (the
  telescope simulator always reports one).
- Polar alignment needs the site only roughly (field notes, 22:48). The total error
  is the angle between the fitted axis and the pole, both in the equatorial frame;
  its split into altitude and azimuth (`align/polar.py` `altaz`) needs the zenith,
  i.e. the latitude, and the sidereal time, i.e. the longitude. A site a few km off
  changes nothing measurable; a degree off turns the split by about a degree. A
  default at 0°, 0° is not rough: it turns it by tens of degrees.
- Some of a step's needs are met elsewhere and long before (the site and the plate
  solver with the box, the devices by Connect, which also sends the mount the site
  and the time); others the step settles on its own screen (polar alignment goes
  to its start; framing chooses a target).

## Decision

- **The server works out what blocks each step** of the checklist and publishes it
  in the state as `preparation`: for `polar_align`, `focus`, `frame` and `guide`,
  whether it `applies` (the active profile has the devices it uses) and its
  `blockers`, the most basic first, each with a `reason`, the `role` for a device
  that is not ready, and a message (`nocs.preparation`). The services that run the
  steps refuse on the same grounds, so the checklist, the steps' screens and the
  server agree.
- **Blockers are what the user fixes elsewhere**, and where:

  | Reason | Steps | Fixed in |
  | --- | --- | --- |
  | `not_connected` (no role: the profile; a role: that device) | all | Connect (Rig) |
  | `no_site` | polar align | the box's sites (Rig → Site; a new site when none is saved) |
  | `no_solver`, `no_database` | polar align, frame | the box (ASTAP and its databases come with the image) |
  | `parked` | polar align, frame, guide | the mount (Rig) |
  | `no_phd2` | guide | PHD2 (Guiding) |

  What a step settles on its own screen is not a blocker: where the mount points,
  a target to frame, a job holding the mount for a while.
- **The checklist's next step is the first one not done that can run.** A step that
  cannot run shows each blocker and a link to where it is fixed, and has no button;
  a later step that can run keeps its text button. A step done tonight stays done.
  Steps come from the profile's roles, so before connecting they show, blocked by
  Connect.
- **Polar alignment measures with the box's active site, never the mount's own**
  (amends ADR 0034 and 0038's "everything that needs the site reads the active one":
  the fallback to the mount's site is gone). The mount still gets the active site
  at Connect. The polar screen says that a rough site is enough, and what is missing
  when there is none.
- **The box's first run gets no site step for now.** A site step belongs in
  `boxsetup.ts` once a site can come from the mount, the GPS or the phone without
  typing coordinates (rc4 field notes, 22:48: a new site from the mount and the GPS);
  until then the checklist and the polar screen send the user to add one.

## Consequences

- The checklist never offers a step that the server would refuse for a reason the
  user must fix elsewhere, and says where to fix it.
- A mount that knows its site is no longer enough for polar alignment: the owner
  saves the site once (or, later, takes it from the mount or the GPS).
- The rule extends to new steps (a sequence, calibration frames) by adding their
  needs to `nocs.preparation`.
- `preparation` follows the state it reads (equipment, sites, solver, the mount's
  park, the main camera's field, PHD2's connection) and is recomputed when those
  change, not on every mount position update.
