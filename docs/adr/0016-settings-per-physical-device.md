# 0016. Settings per physical device: filter names by serial number

Date: 2026-10-31 · Status: Accepted

## Context

Stage 2.8 gives the filter wheel names: they choose the filter in Live view,
name the folders frames are saved in (ADR 0013) and go into the `FILTER` FITS
header. Facts that shape the decision:

- The order of the filters belongs to a wheel, not to a rig. The maintainer has
  three wheels, one per camera, each loaded in a different order, and a profile
  (ADR 0011) may be connected with any of them.
- INDI drivers keep the names (`FILTER_NAME`) in their configuration file, which
  is named after the device. Every ZWO wheel is called "ZWO EFW", so all of them
  share one set of names: after swapping wheels the driver shows the names of
  the previous one.
- ZWO's wheel driver publishes the wheel's serial number (`Serial Number.SN`,
  e.g. `33AF6560C0000000` on the lab EFW). There is no standard INDI property
  for it, and the simulator has none.
- ADR 0011 left open how to tell two identical devices on one driver apart
  ("e.g. by serial number").

## Decision

- NOCS keeps settings for **physical devices**, apart from profiles, in the
  configuration directory. The first are the filter wheels:
  `filter-wheels.json` maps a wheel's key to its label and one name per slot.
- A wheel's **key** is `serial:<number>` when its driver publishes one, and
  `device:<INDI device name>` otherwise (simulators, other drivers).
- When a wheel becomes ready, NOCS looks it up and sends the driver its names
  if they differ. A wheel NOCS has not seen is recorded with the names its
  driver has, marked as new, and the app asks the user what sits in each slot.
- Names are edited per wheel (Rig → the wheel), slot by slot, with the common
  filter names offered first so that every wheel names the same filter the same
  way; the catalog groups frames by these names. Two slots may not share a name
  (except "Empty"), since filters are also chosen by name.
- Profiles do not hold filter names; they still only say which device plays the
  filter wheel role.

## Consequences

- Filter names, saved folders and FITS headers follow the wheel actually
  attached, whatever profile is connected.
- A wheel without a serial number is known by its device name: two such wheels
  of the same model share their names, as they do in INDI itself.
- Other per-device settings (filter focus offsets, focuser backlash, telling
  identical cameras apart) can use the same keys later.
- That every EFW reports a different serial number is assumed, not checked: the
  lab has one wheel.
