# NOCS — New Observatory Control Server

NOCS is a standalone observatory-control server for amateur astrophotography. One install, one web UI, one bearer token — no KStars, no Ekos, no INDI panels to touch.

> **Status:** v0.1 server skeleton (Plan A), abstract device layer + INDI adapter (Plan B), target service + bundled catalogs (Plan C), **ImageStoreService** with `/api/images/*` (Plan D), **plate solving + optional ASTAP fetch-install** (Plan E), and **SafetyService** with YAML rules and `/api/safety/*` (Plan F) are implemented; imaging sequences and the web client are not yet present.

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

### Target picker

With an active observatory row in place, the target API is live:

```bash
TOKEN="..."  # printed on startup
curl -sS -H "Authorization: Bearer $TOKEN" -X POST \
     -H "Content-Type: application/json" \
     -d '{"name":"Backyard","latitudeDeg":40.0,"longitudeDeg":-74.0,"elevationM":10,"timezone":"America/New_York","horizonMaskJson":"[]"}' \
     "http://localhost:8080/api/observatories"

curl -sS -H "Authorization: Bearer $TOKEN" "http://localhost:8080/api/targets/search?q=M31"
curl -sS -H "Authorization: Bearer $TOKEN" "http://localhost:8080/api/targets/planet:jupiter"
```

### Captures & thumbnails (Plan D)

After triggering an exposure on a connected camera (real driver or `indi_simulator_ccd`):

```bash
TOKEN="<printed token>"
curl -s -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"durationSeconds":30,"filter":"L","target":"M31","step":"L_30s","seq":1}' \
     http://localhost:8080/api/cameras/<camera-id>/expose

curl -s -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8080/api/images?device=<camera-id>"

# The response includes the new image id; download the FITS and the thumbnail:
ID=<id-from-list>
curl -s -H "Authorization: Bearer $TOKEN" \
     -o capture.fits "http://localhost:8080/api/images/$ID.fits"
curl -s -H "Authorization: Bearer $TOKEN" \
     -o capture.thumb.jpg "http://localhost:8080/api/images/$ID/thumb.jpg"
```

### Plate solving (Plan E)

After saving an image via `/api/cameras/{id}/expose`, plate-solve it. The default `nocs.platesolving.solver=astap` requires an installed ASTAP CLI + H18 star DB. If you already have ASTAP, point the config at it; otherwise opt in to the bundled fetch-and-install:

```bash
TOKEN="<printed token>"

# Check whether ASTAP is detected on this machine:
curl -s -H "Authorization: Bearer $TOKEN" \
     http://localhost:8080/api/platesolving/install

# Opt in (one-time): edit data_dir/config.yaml to set
#   nocs.platesolving.install.allow-network: true
#   nocs.platesolving.install.binary-url-template: <pinned URL>
#   nocs.platesolving.install.binary-sha256.<your-platform>: <pinned hex>
#   nocs.platesolving.install.db-url: <pinned URL>
#   nocs.platesolving.install.db-sha256: <pinned hex>
# Restart NOCS, then:
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"acceptLicense": true}' \
     http://localhost:8080/api/platesolving/install

curl -s -H "Authorization: Bearer $TOKEN" \
     http://localhost:8080/api/platesolving/install/progress

# Solve a saved image:
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"image_id": 42}' \
     http://localhost:8080/api/platesolving/solve
```

### Safety (Plan F)

NOCS ships a YAML rule engine plus an always-available emergency stop:

- `safety.yaml` lives in your data dir (copied from `safety.example.yaml` on first run). Reload after edits:
  `curl -X POST -H 'Authorization: Bearer <token>' http://localhost:8080/api/safety/rules/reload`.
- Supported conditions: `humidity_above`, `rain_detected`, `altitude_below`, `sensor_offline`.
- Supported actions: `pause_sequence`, `abort_and_park`, `e_stop`.
- Push a sensor reading (for example from a weather script):
  `curl -X POST -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json' \
       http://localhost:8080/api/safety/sensors/readings \
       -d '{"sensor":"weather","values":{"rain_detected":true}}'`.
- Emergency stop:
  `curl -X POST -H 'Authorization: Bearer <token>' http://localhost:8080/api/safety/e-stop`.
- After an E-stop, devices stay in `E_STOPPED` and reject commands until you reset:
  `curl -X POST -H 'Authorization: Bearer <token>' http://localhost:8080/api/safety/reset`.

The catalog is built-in (Messier, Caldwell, NGC+IC, IAU named stars, solar system). To refresh from upstream, run `./scripts/fetch-catalogs.sh` and commit the outputs.

Set `nocs.targets.online-resolver: true` in your `config.yaml` to fall back to SIMBAD when a name is not in the bundled catalog.

To build a self-contained archive for **this machine’s** OS/arch (bundled JDK 25 via `jlink`):

```bash
./gradlew runtimeDist verifyArchiveSize
# e.g. build/distributions/nocs-<version>-linux-x86_64.tar.gz on Linux x86_64
```

Other platforms use the same Gradle targets on a **matching** host, or set an explicit target (must match the runner — foreign targets are not cross-linked from one OS):

```bash
./gradlew -Pnocs.packaging.target=linux-arm64 runtimeDist verifyArchiveSize
./gradlew -Pnocs.packaging.target=windows-x86_64 runtimeDist verifyArchiveSize
```

CI builds all three archives on native `ubuntu-latest`, `ubuntu-24.04-arm64`, and `windows-latest` jobs.

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

Captured FITS blobs are written under `data_dir/sessions/<date>/<target>/` with thumbnails alongside, and indexed in the SQLite `images` table (see `GET /api/images`).

## Install (release archives)

Each release publishes three self-contained archives. Pick the one for your machine, unpack it, and run the launcher — no system JDK, no `sudo`, no package manager.

### Linux x86_64

```bash
VERSION=0.1.0    # replace with the release tag without the leading "v"
curl -LO https://github.com/jorjazo/nocs/releases/download/v${VERSION}/nocs-${VERSION}-linux-x86_64.tar.gz
tar xzf nocs-${VERSION}-linux-x86_64.tar.gz
cd nocs-${VERSION}
./bin/nocs
```

### Linux arm64 (Raspberry Pi 4 / 5)

```bash
VERSION=0.1.0
curl -LO https://github.com/jorjazo/nocs/releases/download/v${VERSION}/nocs-${VERSION}-linux-arm64.tar.gz
tar xzf nocs-${VERSION}-linux-arm64.tar.gz
cd nocs-${VERSION}
./bin/nocs
```

### Windows x86_64

In PowerShell:

```powershell
$VERSION = "0.1.0"
Invoke-WebRequest "https://github.com/jorjazo/nocs/releases/download/v$VERSION/nocs-$VERSION-windows-x86_64.zip" -OutFile "nocs.zip"
Expand-Archive nocs.zip -DestinationPath .
cd "nocs-$VERSION"
.\bin\nocs.bat
```

### Verify your download

Each release ships a `SHA256SUMS.txt`:

```bash
curl -LO https://github.com/jorjazo/nocs/releases/download/v${VERSION}/SHA256SUMS.txt
sha256sum -c SHA256SUMS.txt --ignore-missing
```

On Windows, use `Get-FileHash <archive> -Algorithm SHA256` and compare to the matching line in `SHA256SUMS.txt`.

The archive contains a bundled JDK 25 runtime. On first run NOCS creates its data directory (`$XDG_DATA_HOME/nocs` on Linux, `%APPDATA%\nocs` on Windows), copies example configs, and prints a generated bearer token. Point a browser at `http://<host>:<port>/` and use the token for API calls.

## License

NOCS is licensed under the **GNU General Public License v3.0** — see [`LICENSE`](LICENSE).

In short: you can use, study, modify, and redistribute NOCS; any distributed modifications must be released under GPL-3.0 as well, with source code made available. This matches the licensing vibe of the INDI ecosystem that NOCS sits on top of.

## Contributing

Bug reports and design feedback are welcome via issues. See the design spec and plan decomposition under `docs/superpowers/`.
