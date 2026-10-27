# 0010. Separate privileged system helper

Date: 2026-10-27 · Status: Accepted

## Context

Appliance-level ease of use requires OS-level control: Wi-Fi access point and
station modes, mounting USB drives, setting the clock and location, health
monitoring, updates and shutdown. These need elevated privileges. The core
daemon is network-facing.

## Decision

OS operations live in `nocs-system`, a small service with minimal privileges
that exposes a local Unix-socket API used only by nocsd. It uses D-Bus
interfaces (NetworkManager, udisks2, timedated, logind) where available.
nocsd runs as an unprivileged user.

## Consequences

- A compromise or bug in the network-facing daemon cannot directly
  reconfigure the system.
- An extra component to package and version.
