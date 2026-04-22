# NOCS — New Observatory Control Server

NOCS is a standalone observatory-control server for amateur astrophotography. One install, one web UI, one bearer token — no KStars, no Ekos, no INDI panels to touch.

> **Status:** pre-implementation. Design spec is complete; code has not yet been written.

## Who it's for (v0.1)

A **solo amateur astrophotographer on a local network**. Typical setup: one mount, one cooled main camera, one filter wheel, one focuser. Client is a laptop or phone on the same LAN as the NOCS server. No multi-user, no internet exposure, no mobile app in v0.1.

## What it does (v0.1 MVP)

A real imaging session, end-to-end:

1. **Connect** mount, camera, filter wheel, and focuser through the web UI. No config-file editing.
2. **Pick a target** by name (`M31`, `NGC 7000`, `Mars`, …) against a bundled offline catalog (Messier, Caldwell, NGC/IC, named stars, Solar System). Optional SIMBAD fallback.
3. **Slew + plate-solve + sync** automatically.
4. **Autofocus.**
5. **Run a sequence** (N × exposure × filter with between-sub dithering).
6. **Safety:** YAML rule engine reacts to weather/sensor events with pause / abort-and-park / e-stop. A big E-stop button is always one click away.

Out of v0.1 (but architecturally reserved): autoguiding, multi-target scheduler, calibration-frame workflow, meridian flip automation, sky chart in the browser, multi-user auth.

## How it's built

| Layer | Choice |
|---|---|
| JVM | JDK 25, Spring Boot 3, virtual threads |
| Driver backplane | **INDI**, as a supervised child process — invisible to the user |
| Transport | REST for commands, **SSE** for event streams, HTTP GET for FITS blobs |
| Event bus | Project Reactor (in-process) |
| Persistence | SQLite + Flyway; FITS on disk |
| Plate solver | ASTAP (pluggable) |
| Web client | React + Vite + TypeScript |
| Packaging | Self-contained archive per OS+arch, bundled JRE via `jlink` — download, unzip, run |
| Platforms | Linux x86_64, Linux arm64 (Raspberry Pi 4/5), Windows x86_64 |

## Design spec

Full design is in [`docs/superpowers/specs/2026-04-21-nocs-v0.1-design.md`](docs/superpowers/specs/2026-04-21-nocs-v0.1-design.md). Start there if you want to understand how NOCS is put together before any code lands.

## Comparison with the INDI + Ekos + KStars stack

| Concern | Ekos + INDI + KStars | NOCS v0.1 |
|---|---|---|
| User-facing surface | Three applications, stacked panels, driver tab per device | One web UI |
| Driver ecosystem | INDI (hundreds of drivers) | INDI, via NOCS backplane (user sees none of it) |
| Remote access from a browser | X forwarding / VNC / webapps on top | Native: HTTP server, browser client |
| Scripting | KStars DBus / INDI properties | HTTP REST API from day one |

## Install (planned, not yet available)

```
# Linux / macOS / Raspberry Pi
curl -LO https://github.com/jorjazo/nocs/releases/latest/download/nocs-<version>-linux-<arch>.tar.gz
tar xzf nocs-<version>-linux-<arch>.tar.gz
cd nocs-<version>
./bin/nocs
```

No JRE required on the host. No `sudo`. No package manager. The archive contains a bundled JDK 25 runtime.

On first run NOCS creates its data directory, copies example configs, and prints a generated bearer token. Point a browser at `http://<host>:<port>/` and paste the token.

## License

NOCS is licensed under the **GNU General Public License v3.0** — see [`LICENSE`](LICENSE).

In short: you can use, study, modify, and redistribute NOCS; any distributed modifications must be released under GPL-3.0 as well, with source code made available. This matches the licensing vibe of the INDI ecosystem that NOCS sits on top of.

## Contributing

Too early — there's no code yet. If you have thoughts on the design, open an issue against the design doc.
