# NOCS — notes for Claude

NOCS is a web-first control system for astrophotography rigs on top of INDI.
Read [docs/design.md](docs/design.md), [docs/roadmap.md](docs/roadmap.md) and the
[ADRs](docs/adr/) before planning work; [docs/ux.md](docs/ux.md) for UI work;
[docs/spikes/](docs/spikes/) for measured facts (PHD2 headless, Pi 5 performance).

## Working with the maintainer

- Talk in **Spanish**. Code, comments, docs and commit messages in **English**.
- One maintainer, 5–10 h/week: keep phases small and every step testable.
- **Commit and push only when asked.** Commits are signed off (`git commit -s`,
  DCO) and end with the Co-Authored-By line. After a push, check that CI passes
  **without blocking on it**: watch the run in the background
  (`gh run watch <id> --exit-status` as a background command), keep working on
  the next step meanwhile, and fix a failure when the notification arrives.
  The same goes for long local test runs.
- Propose a plan in stages before large changes; record significant decisions as
  a new ADR rather than editing an accepted one.

## Layout

```
server/   Python package `nocs` (nocsd): indi/ (protocol + async client, driver
          FIFO + catalog), devices/ (typed facades), equipment/ (profiles,
          roles, connect service), imaging/ (capture, preview worker),
          storage/ (destinations, layout, FITS headers, SQLite catalog),
          mount/, focus/, filters/ (services by role; filter names per wheel),
          guiding/ (PHD2: service, settings it imports, JSON-RPC client,
          guide steps and RMS),
          solving/ (ASTAP, fields of view), pointing/ (solve and sync, centre),
          sky/ (a night's almanac at the site, targets' visibility),
          targets/ (bundled OpenNGC catalog and its search, ADR 0019),
          system/ (nocs-system, the root helper: stdlib + anyio only, ADR 0027),
          state/ (versioned store), services/ (indi_bridge), api/ (FastAPI
          REST + WebSocket, schemas, schema export)
web/      Svelte 5 + TypeScript PWA: styles/ (tokens), lib/ (api, live state,
          auth, router, i18n/ with en.ts as the source, prefs), components/,
          screens/ (dev/ is the old INDI property browser at #/dev)
dev/      compose.yaml (INDI simulators + GSC catalog + driver FIFO in dev/.run,
          headless PHD2), astap/ (solver install), profiles/ (simulator rig),
          catalog/ (builds the bundled target catalog),
          tools/ (indi_record, phd2_record, fake_ppba),
          bench/, spikes/, pi/ (lab Pi flashing and setup)
packaging/ deb/ (the nocs .deb: build.sh, test.sh), image/ (the Pi 5 image, arm64 only; ADR 0025, 0026)
docs/     design, roadmap, ux, adr/, spikes/
```

## Commands

```sh
docker compose -f dev/compose.yaml up -d --build  # INDI simulators :7624, PHD2 :4400
cd server && uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright   # strict
dev/astap/install.sh  # ASTAP + D05 in dev/.astap (slow download; ADR 0018)
NOCS_TEST_INDI=localhost:7624 NOCS_TEST_INDI_FIFO=../dev/.run/fifo \
  NOCS_TEST_INDI_UPLOADS=../dev/.run/uploads NOCS_TEST_ASTAP=../dev/.astap/astap_cli \
  NOCS_TEST_PHD2=localhost:4400 NOCS_TEST_PHD2_SETTINGS=../dev/.run/phd2.phd uv run pytest
# real night frames for the solver: NOCS_TEST_FRAMES=<dir of FITS lights>, with D50
# (NOCS_TEST_ASTAP_DB=<dir>): D05 fails dense Milky Way fields
cd web && pnpm install && pnpm check && pnpm build
pnpm gen:types        # after changing server/src/nocs/api/schemas.py (CI checks)
NOCS_WEB_DIR=web/dist NOCS_INDI_FIFO=dev/.run/fifo NOCS_INDI_DRIVERS_DIR=dev/.run/drivers \
  NOCS_INDI_UPLOAD_DIR=/run/indi/uploads NOCS_INDI_UPLOAD_DIR_LOCAL=dev/.run/uploads \
  NOCS_PHD2_SETTINGS=dev/.run/phd2.phd NOCS_PHD2_INDI_HOST=indi \
  uv run --project server nocsd               # http://127.0.0.1:8000
# profiles live in ~/.config/nocs/profiles/ (NOCS_CONFIG_DIR); dev/profiles/ has the simulators
# the first visit sets the owner passphrase and pairs that browser (ADR 0014);
# rm ~/.config/nocs/auth.json and restart nocsd to start over. From a shell:
curl -c jar -H 'Content-Type: application/json' -d '{"passphrase": "…", "name": "curl"}' \
  localhost:8000/api/auth/pair && curl -b jar localhost:8000/api/state
# other host names than IPs, localhost and *.local are refused (DNS rebinding):
# NOCS_HOSTNAMES=nocs.lan,rig.example lists extra ones; tests add `testserver`
```

```sh
packaging/deb/build.sh && packaging/deb/test.sh packaging/out/nocs_*_amd64.deb  # .deb, installed with systemd
```

CI runs all of the above (INDI simulators included) on every push to `main`; the
packages workflow builds and installs the .deb on amd64 and arm64.

## Conventions and decisions to respect

- **pyright strict** and ruff are mandatory; no `Any` leaking from libraries
  without a narrow `pyright: ignore` and a reason.
- **State goes through `StateStore`**; clients get snapshot + patches with an
  epoch. Document new state in `api/schemas.py` (tests validate the live state
  against it) and regenerate the TS types.
- **Every `/api` endpoint needs the paired owner** unless it is listed as public
  or for observers in `api/auth.py` (ADR 0014); never put secrets in the state,
  which observers see. API tests pair their client with `pair_owner(client)`
  (`tests/owner.py`).
- **Device code goes through `nocs.devices` facades**, not raw INDI properties.
  Commands complete on the driver's `Ok` and fail on `Alert`.
- **Concurrency in the API uses anyio** (task groups, `move_on_after`), the ASGI
  server's own model: mixing asyncio TaskGroups with it lost cancellations and
  caused flaky WebSocket tests.
- **Imaging pipeline** (from the Pi 5 spike): JPEG previews (not WebP), OpenCV
  for debayer and downscale, star metrics (`sep`) in a worker process, never on
  the event loop. ASTAP downsampling must be chosen from star size, not `-z 0`.
  Frames arrive by `UPLOAD_LOCAL` when indiserver shares the filesystem (a BLOB
  blocks the event loop ~0.3 s per 26 MP frame on the Pi), are analysed in one
  spawned worker process, and OpenCV calls an RGGB sensor "BG" (ADR 0012).
- **Python runtime:** nocsd should run on a uv-managed Python (3.12/3.13), not
  the system interpreter: scientific deps lack arm64 wheels for Ubuntu 26.04's
  Python 3.14.
- **Target platform:** Ubuntu 26.04 LTS; INDI from `ppa:mutlaqja/ppa` (only
  publishes for the current release; third-party drivers in
  `indi-3rdparty-drivers`), PHD2 from `ppa:pch/phd2`.

## INDI gotchas (all bit us already)

- Drivers define most properties only **after** CONNECT, and some first with
  placeholder values (e.g. `CCD_INFO` at 0×0): wait for readiness
  (`Device.not_ready()`), never assume.
- Right after (re)connecting to indiserver, devices appear gradually; wait for
  `CONNECTION` before using a device.
- Property state conventions vary: tracking reports `Busy` = on, `Idle` = off;
  a disconnected `CONNECTION` is `Idle`, not `Ok`.
- indiserver does not create its `-f` FIFO, and keeps restarting (`-r`) a driver
  that cannot be executed instead of reporting it.
- Expat ≥ 2.6 defers small trailing chunks: the stream parser must `flush()`.
- Drivers reuse `UPLOAD_LOCAL` file names, and indiserver re-sends definitions
  when any client connects: a frame's path is the next *update* of
  `CCD_FILE_PATH`, not its value.
- On ext4, renaming a file over an existing one flushes it to disk first
  (~2 s for a 26 MP frame on the Pi's microSD): move frames to new names only.
- The simulators render real stars only with the GSC catalog (in the dev image);
  their stars are very sharp (HFR < 1 px).
- The CCD simulator draws its stars with the Focuser Simulator's `FWHM`, a
  parabola in the position (best ≈ 36667): a usable V-curve needs ~1000 mm of
  focal length (`SCOPE_INFO`; see `server/tests/simfocus.py`).
- The ZWO EAF reports `FOCUS_MAX` = 100000, above that property's own maximum
  and the 47814 steps `ABS_FOCUS_POSITION` accepts: limits come from the latter.
- Drivers save filter names in `$HOME/.indi` and turn `FILTER_NAME` to Alert when
  they cannot write it (the dev image sets `HOME` for the unprivileged user).
- A ZWO EAF move cancelled by NOCS goes on to its target, and the EAF refuses a
  new move until it gets there ("Error: 5"): abort, wait for it to stop, then move.
- The ZWO EFW never reports `FILTER_SLOT` Busy while it turns (2–3 s per change):
  a filter change shows only as its job.
- INDI's Telescope base class ignores a `TELESCOPE_TRACK_STATE` request equal to
  the switch as it stands, and syncs the switch with the mount only at its next
  poll: right after an abort it can say on while the mount stopped (coordinates
  Idle). `Mount.set_tracking` switches off first in that case.
- The telescope simulator gets a pointing error from its `MOUNT_MODEL` index errors
  (arcminutes); its syncs are alignment points that work only after its alignment
  model is cleared and committed, and stale points later throw its sky far off:
  clear them after a test (`tests/test_pointing_integration.py`).
- Set those index errors with the mount already on the field: changed just before
  a go to, the next frame once landed right on the target, with no error to correct.
- The ZWO AM5/AM7 keeps a sync away from the pole, but at home (Dec −90°) goes
  back to −90° at its next poll.

## PHD2 gotchas

- `phd2 -l` replaces every PHD2 profile, calibration included: import only when the
  settings change, with `AutoLoadCalibration` on (ADR 0022).
- `stop_capture` answers at once; PHD2 refuses `set_connected false` until
  `LoopingExposuresStopped` (or `GuidingStopped`) arrives.
- AppState `Selected` means looping with a star selected (capture active), not
  idle: only `Stopped` is. A star lost while calibrating is waited for forever.
- Xvfb killed with its lock file left behind refuses to start on that display again,
  and PHD2's own lock (`~/phd2.1`, a PID) can name a live process after a power cut,
  leaving PHD2 (even `phd2 -l`) stuck on an invisible dialog: the entrypoint removes
  both.

## Lab hardware

- Lab Pi 5 (Ubuntu 26.04, Docker, uv, ASTAP + D50 in `/opt/astap`):
  `ssh jorjazo@nocs-lab.local`. Its `~/nocs` may not be a clean checkout.
- Reference rig for Phase 2 device priority: ZWO cooled camera, ZWO EFW, ZWO
  EAF, ZWO AM5, Pegasus Pocket Powerbox Advance Gen2, ZWO guide camera; then
  AM7 and iOptron GEM45G. Canon DSLR later.
