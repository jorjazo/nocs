# 0002. INDI as the device backplane

Date: 2026-10-27 · Status: Accepted

## Context

NOCS must control mounts, cameras, focusers, filter wheels, power boxes and
sensors from many vendors, on Linux. Writing drivers is out of scope.

Options considered:

- **INDI:** largest Linux driver ecosystem, mature, large community (KStars/Ekos,
  StellarMate), official packages for Ubuntu including third-party drivers.
  Network XML protocol; orchestration is left to clients.
- **INDIGO:** modern and fast, JSON protocol, server-side "agents" for
  imaging, guiding and alignment. Smaller community, depends on few people,
  custom license, few clients outside macOS. Using its agents would put the
  core of the product (workflows) outside NOCS.
- **ASCOM Alpaca:** network-native and cross-platform in principle, but the
  device ecosystem is Windows-centric.

## Decision

Use INDI as the only device backend for now, talking to `indiserver` over the
INDI XML protocol (no linking against libindi). All workflows are implemented
in NOCS on top of a typed device abstraction, with INDI as one adapter.

## Consequences

- NOCS owns orchestration, which is the bulk of the work and the core value.
- No license coupling with INDI or its drivers.
- An INDIGO or Alpaca adapter remains possible behind the same abstraction.
- NOCS needs a robust async INDI protocol client.
