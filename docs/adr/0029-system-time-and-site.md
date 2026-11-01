# 0029. System time and site from NTP, a GPS or the client

Date: 2026-10-31 · Status: Proposed · Supersedes in part: [ADR 0015](0015-mount-control-and-client-time.md) (client time)

## Context

ADR 0015 made clients report their clock and had NOCS correct the timestamps it
writes itself when the system clock is more than 5 s off, without ever changing
the system clock: that is privileged, and nocs-system did not exist. Phase 6
builds nocs-system (ADR 0027). Facts:

- In the field the Pi has no network time. The Pi 5 has a real-time clock
  (`rpi-rtc`) that keeps time only with a battery on its connector; without one the
  clock starts where it stopped, possibly days off.
- Ubuntu 26.04 runs **chrony** (`rtcsync`, `makestep 1 3`): it steps the clock in
  its first updates, then slews, and keeps the RTC in step.
- timedated refuses to set the time while network time synchronisation is on.
  chrony accepts manual time (`chronyc settime`) when its configuration has the
  `manual` directive, but only as one more sample for its own estimate; with no
  source at all, nothing else adjusts the clock, and stepping it directly is
  exact.
- **gpsd** reads USB GPS receivers and feeds chrony as a reference clock (shared
  memory or socket). A GPS without a PPS signal gives time to within tens or
  hundreds of milliseconds, plenty for pointing and FITS headers; it also gives
  the site.
- Other things read the system clock directly: drivers' FITS keywords
  (`OBJCTALT`, `AIRMASS`, ADR 0015), PHD2's logs, the journal, file times.
- Browsers give geolocation only in a secure context, which v0.1 does not have
  (ADR 0028).

## Decision

- **chrony is the only thing that disciplines the clock**, with three kinds of
  source, best first: a GPS through gpsd, NTP servers when the box is online, and
  the client's time.
- **Client time sets the system clock** through nocs-system (`time.set`: `date
  --set`, then `hwclock --systohc` where there is an RTC) when chrony has no
  synchronised source (nor systemd-timesyncd, on a PC) and the client's time
  differs by more than 5 s. nocs-system checks that again itself, and refuses
  times before 2026 or after 2100. It is not applied while a job runs, so a clock never jumps in the
  middle of an exposure; the first client to connect after boot usually comes
  before any job.
- **nocsd's own correction stays** (ADR 0015): it covers installs without
  nocs-system, and the time before the clock is set. Once chrony is synchronised,
  or the clock was set from a client, the system clock is within the 5 s and the
  correction is zero.
- The `clock` state says where the system time comes from (GPS, NTP, client,
  none) so the app can warn when it is a guess.
- **Site from a GPS:** when gpsd has a 3D fix, the state shows it, and the app
  **offers** it for the active profile when the profile has no site or differs by
  more than 0.01° or 50 m. A site is never changed silently: the mount's site
  follows the profile (ADR 0015).
- The system time zone stays UTC; the client's time zone is used for display.
- The quick start recommends the Pi 5's RTC battery.

## Consequences

- Drivers, PHD2 and logs get the right time once a phone has connected or a GPS
  has a fix, not only what NOCS timestamps itself.
- A box at home with NTP never takes the client's time; a client with a wrong
  clock cannot pull a synchronised box off.
- A GPS replaces the phone as the source of time and site; geolocation waits for
  HTTPS.
- What remains of ADR 0015 (slew pad, pointing, the mount's site and time) is
  unchanged.
