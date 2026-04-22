# NOCS — New Observatory Control Server

NOCS is a standalone observatory-control server for amateur astrophotography. One install, one web UI, one bearer token — no KStars, no Ekos, no INDI panels to touch.

> **Status:** v0.1 server skeleton (Plan A) and abstract device layer + INDI adapter (Plan B) are implemented; targets, imaging sequences, plate solving, and safety are not yet present.

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

The v0.1 work is split into nine implementation plans (A–I); see [`docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md`](docs/superpowers/plans/2026-04-22-v0.1-plan-decomposition.md).

## Comparison with the INDI + Ekos + KStars stack

| Concern | Ekos + INDI + KStars | NOCS v0.1 |
|---|---|---|
| User-facing surface | Three applications, stacked panels, driver tab per device | One web UI |
| Driver ecosystem | INDI (hundreds of drivers) | INDI, via NOCS backplane (user sees none of it) |
| Remote access from a browser | X forwarding / VNC / webapps on top | Native: HTTP server, browser client |
| Scripting | KStars DBus / INDI properties | HTTP REST API from day one |

## Developer quickstart (v0.1 skeleton)

Requirements: JDK 25 on `PATH` (or let Gradle's toolchain auto-provision it).

```bash
./gradlew bootRun
```

On first run NOCS picks a data directory (`$XDG_DATA_HOME/nocs` on Linux, `%APPDATA%\\nocs` on Windows, or `$NOCS_DATA_DIR` if set), copies `config.example.yaml` into it, generates a bearer token, and prints it.

Then in another terminal:

```bash
TOKEN="<printed token>"
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/config
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8080/api/events?topics=system"
```

To build a self-contained archive (linux-x86_64, with a bundled JDK 25):

```bash
./gradlew runtimeTarGz
# Output: build/distributions/nocs-<version>-linux-x86_64.tar.gz
```

Multi-arch archives (linux-arm64, windows-x86_64) land in a later plan.

## Devices & INDI (Plan B)

NOCS uses INDI as its driver backplane. With `nocs.indi.mode=managed` in `config.yaml`, NOCS launches `indiserver` with the configured drivers (using a dedicated Unix socket path under `/tmp/nocs-indiserver-<port>` so it does not clash with another `indiserver` on the machine). With `mode=external` it only connects to an existing `indiserver` on `host:port`. With `mode=disabled`, no device connection is attempted.

Unit tests set `nocs.indi.auto-connect=false` (see `src/test/resources/application.yaml`) so they never open a real INDI socket. The integration test `IndiSimulatorIntegrationTest` runs when `NOCS_INDI_BIN=1` and `indi-bin` is installed (as in CI).

Example `curl` flow against the default simulator driver list in `config.example.yaml`:

```bash
TOKEN="<printed token>"
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/devices
curl -s -X POST -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/devices/telescope-simulator/connect
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"raHours":0.712,"decDegrees":41.269}' http://localhost:8080/api/mounts/telescope-simulator/slew
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"durationSeconds":1.0}' http://localhost:8080/api/cameras/ccd-simulator/expose
```

Captured FITS blobs are written under `data_dir/captures/tmp/` until Plan D adds `ImageStoreService` and canonical session paths.

## Install (release archives, when published)

```
# Linux x86_64
curl -LO https://github.com/jorjazo/nocs/releases/latest/download/nocs-<version>-linux-x86_64.tar.gz
tar xzf nocs-<version>-linux-x86_64.tar.gz
cd nocs-<version>
./bin/nocs
```

No JRE required on the host. No `sudo`. No package manager. The archive contains a bundled JDK 25 runtime.

On first run NOCS creates its data directory, copies example configs, and prints a generated bearer token. Point a browser at `http://<host>:<port>/` and use the token for API calls.

## License

NOCS is licensed under the **GNU General Public License v3.0** — see [`LICENSE`](LICENSE).

In short: you can use, study, modify, and redistribute NOCS; any distributed modifications must be released under GPL-3.0 as well, with source code made available. This matches the licensing vibe of the INDI ecosystem that NOCS sits on top of.

## Contributing

Bug reports and design feedback are welcome via issues. See the design spec and plan decomposition under `docs/superpowers/`.
