# 0015. Mount control: slew pad dead man's switch and client time

Date: 2026-10-30 · Status: Accepted

## Context

Stage 2.9 moves the mount from the phone. Facts that shape the decision:

- INDI's manual motion (`TELESCOPE_MOTION_NS/WE`) starts on a switch and runs
  until another switch stops it. Neither the driver nor the ZWO mounts stop by
  itself: a phone that loses Wi-Fi with a button down leaves the mount slewing
  into cables, the tripod or the pier.
- Drivers ignore a repeated start without answering, and treat a change of
  direction on an axis as a stop (INDI's Telescope base class).
- INDI mounts take apparent coordinates of the date ("JNow"); catalogs give
  J2000. libindi converts with ERFA (CIRS right ascension minus the equation of
  the origins). pyerfa comes with astropy.
- The ZWO AM5 and AM7 share one INDI driver (`indi_lx200am5`, whose device is
  always called "ZWO AM5"). They report neither alt/az nor, at times, their
  pier side, have altitude limits that are off by default, and keep their own
  clock, which they do not set by themselves (the lab AM7 said 2000-01-01).
- In the field the Pi has no network time; without a battery its clock starts
  where it stopped, possibly days off. Setting it is privileged (phase 6,
  ADR 0010). Until HTTPS (phase 6) the browser gives no geolocation (ADR 0014),
  but it does give its clock.

## Decision

### Slew pad

- A **dedicated WebSocket**, `/api/mount/pad`, owner only (default deny,
  ADR 0014) and closed when the device is revoked. Each message is the whole
  state the client holds, `{ns, we, rate}`, repeated every **0.25 s** while a
  button is down and sent once with nulls to let go. Repeating it is harmless.
  REST with keepalives was rejected: one request per keepalive, and no prompt
  notice of a dropped connection.
- **Dead man's switch in the server:** the mount stops when the client lets go,
  after **1 s** without a message (counted from the last message received, so
  sending or commanding never extends it), when the socket closes, on a bad
  message, when the task is cancelled (nocsd stopping) and on any abort. A
  stop that the driver does not confirm becomes `TELESCOPE_ABORT_MOTION`.
- After a stop the client did not ask for, the pad is **latched**: it does
  nothing until the client lets go, so a phone that comes back from a dropout
  with a finger still down does not resume.
- While moving, a pad holds the `mount` lock through a **reservation**
  (`JobManager.reserve`) rather than a job: each tap would otherwise push
  exposures out of the jobs list. Go to, park and home are refused meanwhile;
  `mount.moved_by` names the device at the pad.
- When the mount becomes ready with motion on and no pad holding it (nocsd
  died mid-move), NOCS stops it.
- A rate change while moving stops and restarts the axes: drivers apply a new
  rate on the next start.

### Pointing

- Go to (J2000 or JNow), park and home are **jobs** that lock the mount;
  cancelling one aborts the motion. `POST /api/mount/abort` stops everything
  regardless of locks.
- J2000 → JNow with ERFA as libindi does; UT1 is taken as UTC, polar motion as
  zero, refraction ignored (well under an arcsecond of pointing; geometric
  altitudes).
- A go to below the horizon (altitude 0°) is refused when the site and the time
  are known, unless `force`. The site is the profile's, or else the mount's.
- **Go to alt/az** (the zenith for a flat panel) converts once at the start,
  slews without tracking and switches tracking off when the driver tracks
  anyway. It needs the site and a client-confirmed time.
- Mount limits (altitude, meridian) are published read only for now.

### Client time

- Clients report their clock (`POST /api/clock`, with their time zone) every
  time they connect. NOCS keeps that reading together with the monotonic clock,
  so later corrections of the system clock (NTP getting through) do not move it.
- If the system clock is more than **5 s** off, NOCS uses the client's time,
  advanced by the monotonic clock, for what it timestamps itself: `DATE-OBS`
  (rewritten from the driver's, with `CLOCKCOR` recording the correction), the
  night of a frame and its catalog start time, and the mount's clock. The state
  (`clock`) says so, for the UI to warn. The system clock is never changed.
- Whenever the mount becomes ready, NOCS sends it the **site and then the
  time** (as soon as a client has reported its clock), so the mount is right
  even when no phone is open then. Measured on the lab AM7: after power-on it
  answers every go to with an error (`e` to `:MS#`, "Slew failed (-1)" in
  INDI) until it gets its site, and the site its driver shows is only the
  driver's saved configuration, not what the mount has. EKOS does the same on
  connect. The site is the profile's, or else what the driver shows;
  `PUT /api/mount/site` sends another one. A go to is refused, with that
  reason, until both were sent; the state says whether they were and compares
  the mount's site with the profile's (0.1° tolerance).

## Consequences

- A lost phone, a dead Wi-Fi link or a crashed browser stops the mount within
  about a second; a hung nocsd event loop would not, which the imaging pipeline
  already avoids (ADR 0012).
- Clients must keep sending while a button is down; a pad UI that sends only on
  press and release would stop after 1 s.
- Frame times are right even on a Pi that booted days behind, as long as a
  phone connected; headers the driver computes from its own clock (`OBJCTALT`,
  `OBJCTAZ`, `AIRMASS`) are not corrected yet.
- Nothing checks the site against reality before phase 6 (geolocation or GPS);
  saved sites shared by profiles are left for later.
