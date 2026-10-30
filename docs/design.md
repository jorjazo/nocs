# NOCS — Product and Architecture Design

Status: draft · Last updated: 2026-10-27

This document describes what NOCS is, who it is for, and how it is built.
Individual decisions are recorded with their rationale in [ADRs](adr/); this
document is the big picture that ties them together.

---

## 1. Vision

Dedicated astrophotography appliances proved that most imagers want a rig that
"just works" from a phone: connect, polar align, focus, pick a target, start a
sequence, go to sleep. They also lock users into one vendor's hardware.

The open ecosystem (INDI, KStars/Ekos, PHD2, ASTAP) already supports almost
every device and has every algorithm needed, but is aimed at experts and
desktop screens.

**NOCS brings appliance-level simplicity to the open ecosystem**: a server that
runs on any Linux computer at the telescope, controls any INDI-supported
hardware, and is operated through a beautiful, touch-first web app.

### Goals

1. A first-time user can go from power-on to an unattended imaging session
   using only a phone, guided by the app.
2. The session is owned by the server: clients can connect, disconnect, or
   switch devices without affecting it.
3. Works fully offline in the field. Network access is never required.
4. Hardware-agnostic: anything with an INDI driver can be used.
5. Open source, open formats, no lock-in.

### Non-goals (for now)

- Planetary / lucky imaging (high-speed video capture).
- EAA / live stacking.
- Multiple simultaneous imaging rigs on one server (dual rig).
- Observatory automation: roofs, domes, weather safety (see §13).
- Image post-processing beyond what is needed for previews and quality metrics.
- Windows / ASCOM support.

## 2. Target user and UX principles

The primary user is the **appliance user**: someone who wants to image, not to
configure software. Advanced users must be able to reach every relevant
setting, but defaults must be good enough that most never need to.

Principles:

1. **Workflows over devices.** The main navigation follows the night
   (setup → align → focus → frame → sequence → monitor), not the device tree.
2. **Opinionated defaults, visible escape hatches.** Every automatic decision
   can be inspected and overridden under an "advanced" disclosure.
3. **Never lose a night.** Failures (clouds, lost guide star, cable glitch)
   trigger recovery, not aborts. Abort only what is unsafe.
4. **Phone first, one hand, in the dark.** Large touch targets, red night mode,
   no hover-dependent interactions, readable at arm's length.
5. **Tell the user what is happening.** Long operations show progress, current
   step and estimated time; failures explain the cause and the next step.
6. **Everything is observable.** All state is visible from any client; logs and
   session reports are always available.

## 3. System overview

```
┌──────────────── Clients: PWA in any browser (phone / tablet / desktop) ───────────────┐
│  Svelte + TypeScript · touch-first · night mode · i18n (en, es) · no local state       │
└───────────────┬───────────────────────────────┬───────────────────────┬───────────────┘
        REST (commands, config)      WebSocket (state, events)    HTTP (previews, files)
┌───────────────┴───────────────────────────────┴───────────────────────┴───────────────┐
│ nocsd — core daemon (Python, asyncio, unprivileged)                                    │
│                                                                                        │
│  API layer ─── State store (single source of truth, versioned) ─── Event bus           │
│                                                                                        │
│  Workflows: sequencer · autofocus · polar alignment · solve & center · meridian flip   │
│             guiding control · safety                                                   │
│                                                                                        │
│  Imaging pipeline: FITS write · debayer · stretch · preview · star metrics (HFR)       │
│  Storage & catalog: files on disk + SQLite                                             │
│  Equipment: profiles, optical trains, device roles                                     │
│  Device layer: device abstraction ── INDI adapter (async XML protocol client)          │
└──────────┬──────────────────────────────┬─────────────────────────┬───────────────────┘
           │ INDI XML :7624               │ JSON-RPC :4400          │ CLI
┌──────────┴───────────┐        ┌─────────┴─────────┐     ┌─────────┴─────────┐
│ indiserver + drivers │        │ PHD2 (guiding)    │     │ ASTAP (solving)   │
└──────────────────────┘        └───────────────────┘     └───────────────────┘

┌───────────────────────────────────────────────────────────────────────────────────────┐
│ nocs-system — privileged helper: network · storage · time · health · updates · power   │
│ (local API, consumed only by nocsd)                                                    │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

## 4. Components

### 4.1 nocsd (core daemon)

A single Python asyncio process running as an unprivileged `nocs` user. It owns
all session state and is the only component clients talk to.

Internal modules, with dependencies flowing downward only:

| Module | Responsibility |
|---|---|
| `api` | REST endpoints, WebSocket hub, static file serving, auth |
| `workflows` | Long-running jobs: sequencer, autofocus, polar alignment, solve & center, meridian flip |
| `guiding` | PHD2 process lifecycle and JSON-RPC client |
| `solving` | ASTAP invocation, solution parsing, hints from optical train and mount |
| `imaging` | Exposure orchestration, FITS writing, preview generation, star metrics |
| `storage` | File layout, destinations, SQLite catalog of sessions and frames |
| `equipment` | Equipment profiles, optical trains, device role assignment |
| `devices` | Typed device abstraction (Camera, Mount, Focuser, FilterWheel, PowerBox, Weather…) |
| `devices.indi` | INDI adapter: async XML protocol client, property mapping to typed devices |
| `state` | Versioned state store, snapshots and patches, event bus |
| `system` | Client for nocs-system |

The typed device abstraction keeps INDI specifics out of the workflows. It is
the seam where an ASCOM Alpaca or INDIGO adapter could be added later.

### 4.2 nocs-system (privileged helper)

A small separate service with the minimum privileges needed, exposing a local
API (Unix socket) to nocsd only. It wraps OS facilities through D-Bus where
possible:

- **Network:** access point mode (default on first boot), station mode (join
  an existing Wi-Fi network), automatic fallback to AP when the known network is
  lost, Ethernet. Via NetworkManager.
- **Storage:** detection, mounting and ejection of USB drives; free-space
  monitoring. Via udisks2.
- **Time and location:** set system clock and site location from the client's
  clock and GPS on connect (the Pi has no network time in the field); gpsd
  support for USB GPS receivers.
- **Health:** CPU temperature, throttling, under-voltage, memory, disk.
- **USB hotplug:** detect known devices (e.g. ZWO cameras) and suggest drivers.
- **Updates, reboot and shutdown.**

### 4.3 Web client (PWA)

- Svelte + TypeScript, built to static files served by nocsd.
- Installable as a PWA on iOS, Android and desktop; no app store needed.
- Holds no authoritative state: it renders the server's state and sends
  commands.
- Red night mode as a first-class theme; i18n from day one (English, Spanish).
- Designed from mockups of the key flows before implementation (see roadmap).

### 4.4 External engines

| Engine | Use | Integration |
|---|---|---|
| `indiserver` + drivers | All device I/O | Managed by nocsd (start/stop drivers per equipment profile); INDI XML protocol over TCP |
| PHD2 | Guiding, dithering, guide calibration | Managed process, JSON-RPC event server on port 4400. PHD2 connects to the guide camera and mount through INDI itself |
| ASTAP | Plate solving | Command-line invocation with hints (RA/Dec from mount, FOV from optical train); blind solve as fallback |

Each engine runs as a separate process, which keeps licenses cleanly separated
and lets a crash be contained and restarted.

## 5. Equipment model

- **Equipment profile:** a named set of devices with their INDI drivers and
  settings (e.g. "AM5 + 2600MC portable", "GEM45 backyard").
- **Optical train:** a light path with its role and optics:
  `telescope (focal length, aperture, reducer) → [filter wheel] → [focuser] → camera`.
  A profile has one **imaging train** and one **guiding train** (guide scope or
  OAG). FOV and pixel scale are derived from the train and feed the solver,
  framing and guiding.
- **Device roles:** a device can serve one role in a profile (main camera,
  guide camera, mount, focuser, filter wheel, power box, weather sensor…).
- **Site:** latitude, longitude, elevation, horizon (later).

Profiles are stored server-side, exportable as files.

## 6. Client–server protocol

Three channels, each used for what it does best:

1. **REST (HTTP + JSON)** for commands and configuration.
   - Short commands return their result directly.
   - Long operations (exposures, autofocus, slews, sequences) create a **job**
     and return its id immediately. Progress and results arrive as events.
2. **WebSocket** for state and events.
   - On connect, the client receives a full **snapshot** of the state with a
     version number.
   - Afterwards it receives incremental **patches**, each with a sequence
     number. On reconnect, the client asks for patches since its last version;
     if they are no longer available, it gets a new snapshot.
   - Events (job progress, log messages, alerts) travel on the same channel.
3. **Plain HTTP** for binary data: preview images, FITS files, logs, session
   reports. The WebSocket only announces that a new resource is available.
   This keeps binary data cacheable and out of the state channel.

The message schema is defined once (Pydantic models) and exported as an
OpenAPI / JSON Schema, from which the TypeScript client types are generated.

The transport is an implementation detail behind the protocol, so a future
remote-access transport (e.g. WebRTC data channels through a relay) is a
contained change.

### Concurrency between clients

Multiple clients may be connected and all see the same state. Jobs **lock** the
resources they use (e.g. a running sequence owns the mount, main camera,
focuser and filter wheel). Commands touching a locked resource are rejected
with an explanation, or offered as "pause the sequence and do it" where it makes
sense.

## 7. Imaging pipeline

1. Exposure via INDI; the image arrives as a FITS blob.
2. FITS written to the storage destination with complete headers (object,
   coordinates, filter, temperature, gain, offset, focuser position, optics,
   site, timestamps).
3. Preview generation in a worker process: debayer (for color cameras),
   downscale, automatic stretch (midtones transfer, as in common screen
   stretches), WebP/JPEG encode.
4. Star metrics with `sep`: star count, median HFR / FWHM, eccentricity. Used
   for autofocus, quality gates and the session report.
5. Catalog entry in SQLite; event to clients.

Budget target on a Raspberry Pi 5: preview available within ~2 s after a 26 MP
frame is downloaded. To be validated early.

## 8. Storage

- **Destinations:** the internal storage (the microSD on the Pi) is supported
  and used when no external drive is mounted; an external USB SSD is preferred
  automatically and recommended for speed and card wear, never required. NOCS
  keeps a free-space reserve so the OS disk never fills up.
- Default layout: `<destination>/NOCS/<night>/Light/<target>/<filter>/`,
  `Flat/<filter>/`, `Dark/`, `Bias/`, with configurable filename templates
  ([ADR 0013](adr/0013-storage-and-catalog.md)).
- SQLite catalog: nights, targets, frames, metrics, events.
- Access: download through the web app; SMB share for desktop access (later).

## 9. Workflows

### 9.1 Solve and center

Expose → solve with ASTAP using mount position and train FOV as hints → sync
mount → slew to correct → repeat until within tolerance. Blind solve fallback.

### 9.2 Polar alignment

Three-point method: solve at three RA positions, compute the mount axis error,
then live-correct with repeated solves while the user adjusts the altitude and
azimuth knobs. The UI shows the error with a clear "which way to turn" visual.

### 9.3 Autofocus

V-curve sweep around the current position, HFR measured per point, hyperbolic
(or parabolic) fit, move to the minimum with backlash compensation. Quality
checks reject bad runs (clouds, too few stars) and restore the previous
position. Temperature from the EAF / power box sensors is recorded per frame.

### 9.4 Guiding

PHD2 runs as a managed process. NOCS generates/selects the PHD2 profile from
the guiding train, connects equipment, runs calibration when needed, starts and
stops guiding, dithers between frames and monitors guiding RMS. Guiding graphs
are shown in NOCS from PHD2's events.

### 9.5 Sequencer

Model inspired by the most capable existing sequencers: a sequence is a tree
of **containers** and **instructions**, with **conditions** and **triggers**.

- Instructions: slew & center, expose N frames, change filter, autofocus,
  park, warm camera, wait until time/altitude…
- Conditions: loop count, until time, while target above altitude, until dawn.
- Triggers: autofocus on temperature change / filter change / HFR degradation
  / elapsed time; meridian flip; dither every N frames; re-center on drift.
- Recovery policies: lost guide star → pause and retry; clouds (no stars) →
  wait and retry; solve failure → retry, then skip target.

The UI exposes this power through simple templates first ("image this target
with these filters tonight"), with the full tree editor as an advanced view.

### 9.6 Safety (foundation for observatories)

A core notion of **safe / unsafe**: an unsafe condition (e.g. user-configured
weather limits from a sensor, end of night) pauses the active sequence and
parks the mount. Observatory devices will plug into this later.

## 10. Security

- **First-run setup** sets an owner passphrase.
- Clients **pair** once with the passphrase and receive a long-lived device
  token; tokens can be listed and revoked.
- Optional **observer** role: read-only access without pairing, for showing
  the session to others.
- Authentication exists from the first release because remote access is a
  long-term goal; local-only operation must still be frictionless.

## 11. Networking

- First boot: access point `NOCS-xxxx` with a printed default password; the
  web app is reachable at a fixed address and at `nocs.local` (mDNS).
- Station mode to join home Wi-Fi; Ethernet supported.
- If the station network is lost, fall back to access point automatically.

## 12. Deployment

- **Base OS:** Ubuntu Server LTS (arm64 and amd64), because the official INDI
  PPA provides the complete driver set (including the ZWO and gphoto drivers)
  for it. One base for Raspberry Pi images and PC installs.
- **Raspberry Pi image:** Ubuntu Server for Pi customized with INDI, PHD2,
  ASTAP + star database and NOCS preinstalled. Booting from USB SSD supported.
- **Packages:** `.deb` packages for NOCS components from a project apt
  repository.
- **Development:** a container image (Ubuntu + INDI + simulators + PHD2 +
  ASTAP) so development and CI work on any Linux host without real hardware.

## 13. Future directions

In rough order of expected value:

1. Remote access outside the LAN (relay or VPN-style), with the same protocol.
2. DSLR support polish (Canon via gphoto).
3. EAA / live stacking.
4. Observatory: roll-off roofs, domes, safety monitors, weather-driven
   automation.
5. Additional device backends (ASCOM Alpaca, INDIGO).
6. Multiple rigs per server; multi-server dashboard.

## 14. Repository layout

Monorepo:

```
server/      Python package `nocs` (nocsd)
system/      nocs-system helper
web/         Svelte PWA
packaging/   .deb packaging and Raspberry Pi image build
dev/         Development containers, simulator setups, scripts
docs/        Design, ADRs, roadmap, user documentation
```

## 15. Testing strategy

- **Unit tests** for algorithms (HFR, curve fitting, polar alignment math,
  sequencer logic) with recorded data.
- **Integration tests** against INDI simulators (telescope, CCD with a
  synthetic star field, focuser, filter wheel) in CI.
- **Hardware-in-the-loop** tests in the lab with the reference rig.
- **Field tests** at the end of each phase.

Reference hardware (lab):

| Role | Devices |
|---|---|
| Server | Raspberry Pi 5 8 GB (microSD + USB storage) |
| Mounts | ZWO AM5, ZWO AM7, iOptron GEM45G |
| Main cameras | ZWO (cooled and uncooled); Canon DSLR (later) |
| Guiding | ZWO guide camera on guide scope; OAG (secondary) |
| Focuser | ZWO EAF (with temperature sensor) |
| Filter wheel | ZWO EFW |
| Power / environment | Pegasus Pocket Powerbox Advance Gen2 (with temperature/humidity sensor) |

## 16. Open questions and spikes

- ~~**PHD2 headless**~~ — resolved (2026-10): works under Xvfb with profiles
  generated by nocsd and imported with `phd2 -l`. See
  [spikes/phd2-headless.md](spikes/phd2-headless.md).
- ~~**ASTAP on Pi 5**~~ and ~~**preview performance**~~ — resolved (2026-10):
  ~1.3 s hinted / ~4 s blind solves with D50; 26 MP previews in 0.35–0.7 s. See
  [spikes/pi5-performance.md](spikes/pi5-performance.md).
- **AM5 / AM7 driver behavior** in INDI: meridian flip limits, homing, parking.
- **USB bandwidth** on Pi 5 with main camera + guide camera + EAF + EFW + PPBA.
- ~~**Ubuntu release**~~ — resolved (2026-10): the INDI PPA publishes only for the
  current Ubuntu release, now 26.04 LTS, with third-party drivers bundled in
  `indi-3rdparty-drivers` for amd64 and arm64. NOCS follows the current LTS.
