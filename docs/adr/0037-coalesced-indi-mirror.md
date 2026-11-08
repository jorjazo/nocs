# 0037. The state's INDI mirror is coalesced to one update a second per property

Date: 2026-11-01 · Status: Proposed

## Context

The bridge (`nocs.services.indi_bridge`) mirrors every INDI property into the state
(`indi.devices`), and every WebSocket client receives it. The soak test
([spike](../spikes/pi5-soak.md)) measured ~24 patches/s and ~19 kB/s per client
(~70 MB an hour), ~88 % of it this mirror. On the simulators the cameras' snooped
`EQUATORIAL_PE` updates 16 times a second, the mount's `EQUATORIAL_PE` and
`MOUNT_AXES` 8 times, the exposure countdowns 2–3 times. Nothing in NOCS's services
reads the mirror (they use the INDI client and the device facades); in the web, the
developer screen (`#/dev`) shows it, the profile editor reads `DRIVER_INFO` from it to
tell which devices a driver runs, and the rig screen reads `indi.server`.

Two ways to cut it:

- **Send `indi.devices` only to clients that ask** (a field in the `hello`). Removes
  all of it for phones, but changes the protocol: patches with nothing else would
  leave gaps in the versions a client sees, so a client could no longer tell a lost
  patch from a filtered one without a new field; the snapshot would differ per
  client; and the profile editor would have to subscribe, or the drivers' devices
  move elsewhere.
- **Coalesce the mirror in the bridge.** No protocol change; every reader keeps
  working, a little later.

## Decision

The bridge publishes a property's update at once when nothing of it was published
in the last second (`COALESCE`), or when its state changes (Busy, Ok, Alert reach
`#/dev` at once). Otherwise it holds it, and one second after the last publication
it publishes the latest values of every element that changed meanwhile, in one
patch. A property defined again or deleted drops what was held for it.

It also publishes only what differs from the mirror: drivers send every element of
a property with each update, most of them unchanged, and a number's label, format
and limits rarely change, so an unchanged element costs nothing and a number sends
its value alone. The driver messages kept in the state, sent whole with each new
one (a list cannot be patched), go from 50 to 10; `#/dev` shows 5.

The state protocol does not change: the same paths, snapshot and patches, every
version in order.

## Consequences

- On the simulators (mount tracking, the main camera looping 1 s frames), what a
  client receives fell from 36 patches and 22.5 kB a second (87 % the mirror) to 22
  patches and 7.1 kB (48 %); the mirror itself from 19.5 to 3.4 kB/s. The rest is
  NOCS's own state (the mount's coordinates four times a second, the camera, jobs).
- `indi.devices` values can be up to a second old. Code that needs a device's live
  values uses the device facades, as it already does; the mirror is for people.
- If phones on weak Wi-Fi still need less, sending the mirror only to clients that
  ask for it remains possible on top of this, with a protocol change and an ADR of
  its own.
