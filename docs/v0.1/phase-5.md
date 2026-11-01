# Phase 5 plan — Focus & sequence

Status: in progress (autofocus done; sequencer in progress) · Last updated: 2026-10-31 · Roadmap: [Phase 5](../roadmap.md#phase-5--focus--sequence)

Goal: a full unattended night.

**Exit (field test):** start a multi-filter sequence at dusk and wake up to a
completed, parked session — including a meridian flip.

Autofocus came first, while phases 3 and 4 settle the APIs the sequencer will
call (solve and centre, guiding and dithering); it runs inside another job
([ADR 0021](../adr/0021-autofocus.md)). The sequencer is planned below: its
engine and everything that needs only what is on `main` first, re-centring,
dithering and the meridian flip last, once phase 3's centring and phase 4's
dithering have landed.

## Stages: autofocus

| # | Stage | Contents | Check | Status |
|---|---|---|---|---|
| 5.1 | Curve and sweep | `nocs.focus.curve`: hyperbola fitted by weighted least squares on HFR², refined on the HFR, R²; `nocs.focus.sweep`: positions within the travel, extension on one side, moves that approach from one direction with an overshoot, the quality checks, a suggested step ([ADR 0021](../adr/0021-autofocus.md)) | Synthetic curves and one measured on the simulators | Implemented |
| 5.2 | Metrics and frames inside a job | Star metrics in the worker without previews and without dropping frames; a public way for workflows to take a frame inside their own job (shared with phase 3.2's solve job): `CaptureService.take` and `measure` | Simulators: the HFR follows the focuser | Implemented |
| 5.3 | Autofocus job | `AutofocusService.run` inside any job holding the camera, focuser and wheel; its own job from the API; first frame, sweep, extension, fit, final frame, back to the start on failure or cancel; `autofocus` state with the points as they come | Simulators (1000 mm): from focus and from far out of it; no stars; cancel restores | Implemented: `POST /api/autofocus`; on the simulators it found 36282 for a best focus of 36667 (step 4000, R² 0.98) |
| 5.4 | Settings and temperatures | Sweep settings per imaging train in the profile (`imaging.autofocus`, read as saved: no reconnection), backlash per physical focuser (`focusers.json`, ADR 0016 keys; `PUT /api/focuser/backlash`); focuser and ambient temperatures sampled into the catalog every minute (`GET /api/temperatures`); finished runs in the catalog (`GET /api/autofocus/runs`); `AMBTEMP`, `HUMIDITY` and `DEWPOINT` in FITS headers (drivers already write `FOCUSPOS` and `FOCUSTEM`) | Simulators (writable focuser temperature, weather simulator) | Implemented |
| 5.5 | Focus screen | Full-screen flow `#/focus`: settings with an advanced disclosure, live V-curve with the fit, best position / HFR / stars / temperature, result or the reason it failed; from Live view's focuser and the focuser sheet (Tonight's checklist when phase 3 builds it); en/es | Phone, wide, Night mode | Implemented: checked in the browser against the simulators (focused at 36693 for 36667; no stars; Night mode) |
| 5.6 | Lab check | EAF moves and overshoot, time per point with the 26 MP camera, temperatures from the EAF and the PPBA, a clean failure with the cap on; checklist for tuning under the sky | Lab Pi | Done indoors (below); found and fixed: moving back after a cancel in mid-move, and a flat curve from hot pixels. Tuning waits for a clear night |

## Sequencer: what is there to build on (2026-10-31)

- **Jobs do not nest** (`nocs.jobs`). Services offer a job-starting command
  (`goto`, `park`, `select`, `move_to`, `expose`) and, for workflows, a function
  that runs inside a job that already holds the roles: `CaptureService.take` and
  `measure`, `AutofocusService.run`; on phase 3's branch `MountService.slew` and
  `CenteringService.center`. Saving a light frame (`CaptureService._expose`) is
  still private, and the frame's `OBJECT` comes from the storage's global target,
  not from the caller.
- **Locks.** A job locks roles until it ends; `reserve` holds them without a job
  (the slew pad, PHD2's guide camera). Guiding reserves the mount while PHD2
  calibrates or guides (ADR 0023): under a sequence that holds the mount itself,
  that reservation would be refused.
- **Mount.** Park, unpark, home, tracking; `pier_side` (the AM5/AM7 driver does not
  always report it, ADR 0015) and `meridian_limits` (AM5/AM7: the mount can flip by
  itself at a limit). The Telescope Simulator reports `TELESCOPE_PIER_SIDE`;
  whether it changes side after a go to past the meridian is to be measured.
- **Time.** `nocs.clock` gives the client-corrected time (the Pi's clock may be days
  off in the field); `nocs.mount.coords` converts J2000/JNow/alt-az with ERFA,
  which also has the Sun (`epv00`) and the Moon (`moon98`). Phase 3.5 (tonight's
  sky: twilights, altitude curves) is planned, not started.
- **Catalog.** Schema version 2 (temperatures, focus runs). Phase 4.5 plans a
  migration for guiding RMS per frame: whoever lands second renumbers.
- **Guiding** on `main`: connect, loop, guide as a job, stop, settle; dithering
  (4.5), statistics (4.4) and the guiding graph (4.6) are still to come.
- **Supervision** (ADR 0030, stage 6.9) will restart drivers and indiserver and
  leaves USB resets and power cycles to "a running sequence's recovery policy".
- **UI.** The Session tab and Plan tab are placeholders; the router has
  full-screen flows (`#/focus`). The Phase 1 artboards for Sequence and Session
  are on the maintainer's private canvas; `docs/ux.md` §2 summarises them.

## Sequencer: decisions to record

Three ADRs, each written with the first stage that needs it (numbers 0031–0033:
phase 6 holds 0025–0030).

**ADR 0031 — Sequences: model, persistence and who owns the devices** (stage 5.7)

- A sequence is a tree: **containers** (run their children in order, while their
  **conditions** hold, with **triggers** checked between children) and
  **instructions** (leaves: cool, unpark, slew, centre, select filter, autofocus,
  expose N, guide, wait until, park, warm, switch outputs). The root has three
  parts: *start*, *targets* (one container per target, with its exposure plan) and
  *end*, which always runs (completion, a stop, or a failure the policies give up
  on).
- An **exposure plan** is a list of rows (filter, exposure, count, gain, offset,
  binning) and an order: in batches (N of each filter in turn, so that a target
  that sets early still has every filter) or one filter after another.
- **Definitions** are JSON files in the config directory (`sequences/<id>.json`),
  like profiles, exportable; Pydantic models, versioned. **Progress** (frames done
  per row, where the run is) is a checkpoint file in the data directory, written
  after each frame (new name, then rename). **Events and the report's data** go to
  the catalog (a migration: `sessions`, `session_events`, `frames.session_id`).
- **One running sequence, as one job** that locks the main camera, filter wheel,
  focuser and mount for the whole run. Instructions call the services' in-job
  functions (`take`, a new public "take and save" with the target name per frame,
  `select_in`, `AutofocusService.run`, `slew`, `park_in`…), never their
  job-starting commands. The convention for every service: `start` = a job around
  the in-job function. Cooling and power outputs need no lock.
- **Guiding under a sequence:** the sequence connects PHD2 (which reserves the
  guide camera, ADR 0023); when the caller's job already holds the mount, guiding
  does not reserve it, and the sequence stops guiding before it slews.
- **Pause** stops at the next safe point (after the frame in progress, or at once,
  aborting it) and **lends the locks back**: `JobManager.suspend/resume`. While
  paused, Live view, the mount sheet or the focus screen work; resuming takes the
  locks again or says what holds them. A command refused because a sequence holds
  a role says so, and the app offers "pause the sequence and do it" (design §6).
- Conditions use the client-corrected clock (`nocs.clock`), not the Pi's.

**ADR 0032 — Recovery, safety and restarts** (stage 5.12): written as
[ADR 0032](../adr/0032-sequence-recovery-and-restarts.md). Against the outline: a
device gets two retries a minute apart (ADR 0030's restarts happen meanwhile) and
USB resets or power cycles wait until nocs-system offers them; guiding is not stopped
under clouds; after a restart nocsd also connects the profile and waits for a known
time; the meridian guard moves to ADR 0033.

**ADR 0033 — Meridian flip** (stage 5.18, after a spike)

- NOCS flips, not the mount: during a sequence the mount's own automatic flip
  (`MERIDIAN_FLIP`) is off, and NOCS flips at a configured hour angle (default
  5 min past the meridian, which must be inside the mount's `MERIDIAN_LIMIT`).
- Before each frame: if the frame would end past the flip point, wait (frame
  shorter than the wait: wait; otherwise flip first when already past the
  meridian, or wait until it is). The flip: stop guiding, go to the same target,
  check the pier side changed (where the driver reports it; else the solved
  rotation turns by 180°), centre (when 3.3 is on `main`), tell PHD2 to flip its
  calibration (`flip_calibration`) or recalibrate, guide and settle, optionally
  autofocus, carry on. A flip that fails twice ends the session (a mount tracking
  into its pier is the one thing that must not happen).
- A **meridian guard** runs while a sequence exists (paused included): a target
  past the flip point plus a margin with no flip under way stops tracking.

## Stages: sequencer

Estimates in hours. 5.7–5.15 need only what is on `main` today; 5.16–5.18 wait for
phase 4.5 (dithering) and phase 3.3 (centring) to land.

| # | Stage | Contents | Check | h | Status |
|---|---|---|---|---|---|
| 5.7 | Engine | `nocs.sequence`: the model (Pydantic, versioned: containers with a target, `repeat` and conditions; actions; exposure plans in batches or in turn; the *until a time* condition; the autofocus trigger and its reasons), definitions as files (`SequenceStore`), the runner (safe points, pause and pause now, stop with or without *end*, *end* always tried step by step), the checkpoint and resuming from it; no devices yet ([ADR 0031](../adr/0031-sequences.md)) | Unit tests with a fake rig and clock: order, batches, repeats, conditions, every autofocus reason, pause/resume, stop, failures, resume after a crash | 10 | Implemented |
| 5.8 | Sequence job and device instructions | One `sequence` job holding the roles; `JobManager.suspend/resume`; public in-job functions where missing (take and save with the target name, select filter, slew, park/unpark, cool and warm waiting for the temperature, outputs); guiding start/stop without its own mount hold; `sequence` state; `/api/sequences` (CRUD, start, pause, resume, stop); refusals that name the sequence | Simulators: 2 filters × 3 frames, autofocus at the start, park at the end; pause, use Live view, resume | 12 | Implemented: `/api/sequences` (list, get, put, delete, start) and `/api/sequence/{pause,resume,stop}`; `sequence` state with the run and its last 50 events; the job holds main camera, wheel, focuser and mount; in-job `CaptureService.capture` (target per frame), `FilterWheelService.select_in`, `MountService.park_in`/`slew` (as on phase 3's branch), `unpark`/`set_tracking`/`configure`/`set_output` with `job=`; guiding through phase 4.5's `GuidingService.start`/`guide_under` (no mount hold of its own under the sequence). Simulators: 2 filters, autofocus, park in ~100 s |
| 5.9 | Night conditions | Sun altitude and twilights, a target's altitude and its time above a minimum (shared with phase 3.5, whoever lands first writes `nocs.sky`), conditions *until dawn*, *until time*, *while above* and the instruction *wait until* (dusk, time, altitude) | Against an almanac for the lab site; a fake clock | 6 | Implemented on phase 3.5's `nocs.sky`: conditions `until_dawn` (end of a twilight, else sunrise) and `while_above` (apparent altitude over a minimum and the horizon profile), instruction `wait` (a time, dusk, or the target's altitude) checked every 30 s through safe points; a sequence that asks about the sky needs the profile's site. Checked against the almanac for Diaguitas on 2026-11-01 |
| 5.10 | Templates and end of session | "This target, these filters, tonight": a template (target, plan rows, order, start/end, cooling, autofocus settings, guiding, end actions) expanded into a tree; time and disk estimates; *end*: park, warm, outputs off | Template → tree unit tests; simulators run a template | 8 | Implemented: `Template` (target, plan rows, order, dusk, dawn, minimum altitude, cooling, focus at start and on reasons, guiding, end actions, recovery) expanded by `nocs.sequence.template.expand`, kept in the sequence for the builder; `PUT /api/sequences/{id}/template`, `POST /api/sequences/estimate` (frames, integration, duration with 3 s per frame, bytes from the sensor, tonight's window from `nocs.sky`). A fake night from 17:00 at Diaguitas: waits for dusk, focuses, 70 frames, parks |
| 5.11 | Autofocus triggers | The reasons are in the engine (5.7); here they meet the rig: the focuser's temperature and each frame's HFR from the executor, the run's result in the session's events | Simulators: writable focuser temperature and a moved focuser trigger a run | 4 | Implemented: each run's position, HFR and temperature in the session's events; simulators: a 2 °C warmer focuser and a focuser knocked 15000 steps out each brought a run |
| 5.12 | Recovery and restarts | Failure kinds and policies, defaults; events into the catalog (migration 4, after 4.5's); resume after a nocsd restart; the supervisor hook for ADR 0030 (ADR 0032) | Simulators: no stars (`SIM_LIMITINGMAG`), a driver killed mid-frame, nocsd restarted mid-run, PHD2 losing its star | 10 | Implemented ([ADR 0032](../adr/0032-sequence-recovery-and-restarts.md)): policies per kind with defaults, clouds from star counts, lost guide star, waits through safe points; catalog v4 `sessions` and `session_events`; nocsd resumes a run after a restart (connects the profile, waits for the rig and the time). Simulators: a cloud (`SIM_LIMITINGMAG` 0) and a restart of nocsd mid-run. Not yet on the simulators: a driver killed mid-frame, PHD2 losing its star |
| 5.13 | Sequence builder | Plan → Sequence: target (search when 3.4 lands, else typed coordinates), plan rows per filter, order, behaviours (autofocus triggers, guiding, later dither and flip), end actions, time and disk estimates, save and start; the expanded tree read only under Advanced; en/es | Phone, wide, Night mode | 10 | Implemented: Plan → Target / Sequence (`#/plan/sequence`); one sequence per target, id from its name; row and behaviour sheets edit the template live; estimates with when it starts and ends tonight (`starts`, `ends`) and the drive's free space; the steps under Advanced from `POST /api/sequences/expand`. Checked in the browser against the simulators: phone, wide, Night mode, a start that opens the Session tab |
| 5.14 | Session monitor | Session tab: target and row, frame i of N per filter, exposure countdown, latest frame with HFR and stars, sensor temperature, guiding RMS (from 4.4 when there), event timeline, pause / resume / stop; a running-session indicator on the other tabs; "pause and do it" where a command was refused; tablet in two columns with a filmstrip | Phone and tablet, against a simulated run | 10 | Implemented: the monitor above the night's frames; the run's `step` (the instruction at `current`) and event data (filter, guiding on or off, the condition that ended a container) so the timeline is in the user's language; a suspended job says so (`jobs.*.suspended`) and holds nothing for the client; the Session tab's dot; `SequenceHold` in Live view, the device sheets and Focus. Checked in the browser against the simulators: phone and tablet, a pause from Live view, resume, a stop after the frame |
| 5.15 | Session report | `GET /api/sessions` and `/{id}/report`: window, frames and integration per filter, HFR and stars over time, temperatures, autofocus runs, guiding RMS per frame (4.5), events and recoveries, how it ended; a report screen from the Session tab; frames as CSV | A simulated run's report | 8 | Implemented: `GET /api/sessions`, `/api/sessions/{id}/report` and `/frames.csv` (`nocs.api.sessions`): the frames from the frame events' catalog ids, frames under clouds kept and marked (the failure carries the frame's id), per filter frames, integration, median HFR and guiding RMS, autofocus runs with what triggered them, temperatures, failures and recoveries, every event; the report screen `#/session/<id>` from a list of past sessions on the Session tab, with HFR per frame (autofocus runs as dashed lines) and the temperatures. Checked on the simulators' runs |
| 5.16 | Dither | Dither every N frames (4.5's dither and settle), in templates and the builder | Simulators with PHD2 | 4 | Waits for 4.5 |
| 5.17 | Centre and re-centre | Centre at the start of each target and after a flip (3.3's `center`); re-centre when a solve every N frames drifts past a tolerance | Simulators with an injected pointing error | 5 | Waits for 3.3 |
| 5.18 | Meridian flip | Spike first (the Telescope Simulator's and the AM5 driver's pier side after a go to past the meridian; `MERIDIAN_FLIP` off and on); the flip instruction and trigger, the guard, PHD2's calibration (ADR 0033) | Simulators: a target 3 min before the meridian flips mid-sequence; lab AM5/AM7 indoors (lab lock) | 12 | Better after 3.3 |
| 5.19 | A simulated night, lab and field test | `dev/tools/simnight`: a compressed night on the simulators (3 filters, autofocus triggers, a flip, *until time*, park), a shorter version in CI; lab run on the Pi (lab lock); field-test checklist in [field-test.md](field-test.md) | Exit criterion | 8 | |

About 107 h, so the whole phase comes to ~143 h against the roadmap's 80–120 h.
What keeps it there: no tree editor (the tree is read only), one target per
sequence in the builder (the model takes several), no flats.

Shared files: `api/schemas.py` and the generated types (sequence state and
requests), `api/app.py` (wiring), `jobs.py` (suspend/resume), the catalog
migrations, the router (`#/plan/sequence`, the Session tab), and small in-job
additions to the capture, filter, mount, guiding and power services.

## Sequencer: decisions taken (2026-10-31)

1. A nocsd restarted mid-run **resumes by itself** (at most 3 times a night), so the
   night goes on and NOCS keeps watching the meridian.
2. **NOCS flips** at the meridian, with the mount's own flip off during a sequence.
3. Frames under clouds (few stars) are **kept and marked** in the catalog and the
   report; the user decides what to stack.
4. v0.1 scope: the tree is **read only** and the builder takes **one target** per
   sequence (the model takes several).
5. Plans run in **batches of 5 per filter** by default.
6. The Sequence and Session artboards were read from the Phase 1 canvas for
   stages 5.13 and 5.14.

Decided while building (2026-11-01, recommended options):

- **One sequence per target** in the builder, its id made from the target's name
  (`ngc-253`): opening the builder on tonight's target loads its sequence or starts
  one with one row (the wheel's current filter, 20 × 120 s), autofocus at the start
  and every 1 °C, guiding when the profile has a guide camera, park and warm at the
  end. No list of saved sequences in v0.1: the API keeps them all.
- **Edits apply at once** to a draft kept while the page is open; Start saves first.
- The **estimate** also says when imaging would start and end tonight (the target's
  next dark window above the minimum altitude, and the plan or the window, whichever
  ends first), so the tile reads like the artboard: "Imaging time · ends ~01:52".
- *End* stops guiding only when PHD2 guides (a PHD2 shared with someone else is left
  alone).
- The running-session indicator is a **dot on the Session tab** (ux.md's open
  question): always visible, never covering content.
- "Pause the sequence and do it" **pauses at once** (the frame in progress is taken
  again later), shown wherever a screen drives a device the sequence holds, rather
  than retrying a refused command: the user sees why before trying.
- Frames under clouds are **marked in the report** (and its CSV) from the session's
  events, not in the frames table: the catalog stays a record of files, the session
  says why a frame was taken again.
- The tablet's **strip of recent frames** shows their filter, number and HFR, not
  thumbnails: the server keeps only the latest preview.

## Measured

- The CCD simulator reads the focuser simulator's `FWHM`:
  `seeing + 0.5625·((x − best)/5000)²` arcseconds, best ≈ 36667 when the driver
  starts at 50000. Median HFR of 2 s frames at 1000 mm: 1.67 px at focus, 2.6 px
  10000 steps away, 5.4 px 20000 away. At 250 mm it stays under 2.1 px.

## Lab check (2026-10-31, lab Pi 5, indoors with the cap on)

ZWO EAF (serial `0F21209019472401`, firmware 3.2.2) on the 380 mm f/4.7 scope,
ASI2600MC Duo, PPBA as the weather role; a test nocsd beside the maintainer's,
without the driver FIFO.

- **Moves.** The EAF covers 300 steps in 1.3 s, 1500 in 4.8 s (~230 steps/s plus
  ~0.2 s per move). With synthetic stars (a hyperbola at the start + 600 steps)
  a 9-point sweep with step 300 took 23 s, every point reached moving outward
  (overshoots of one step before the first point and before the best focus), and
  it ended exactly on the best focus (6831 for 6831).
- **Cancelling mid-move.** The EAF goes on to the target of the move in progress
  and refuses another one until it gets there ("Failed to set position. Error: 5"),
  so moving back failed and the focuser stayed 300 steps off. Moving back now
  aborts, waits for the focuser to hold still, and tries a refused move once more:
  checked again on the EAF (cancelled at 5931 while moving; it stopped at 5940 and
  went back).
- **With the cap on** the camera's hot pixels pass as ~20 "stars" of 0.82–0.84 px
  HFR in every frame: the first check (10 stars) passes and the sweep runs. It
  ended as a bad fit after extending to 12 points (80 s); a new check for a flat
  sweep (largest HFR under 1.2 × the smallest) now stops it after the first 9
  points (52 s) with its own reason.
- **Time per point** with 2 s exposures of the 26 MP frame and a step of 300: about
  5–6 s (move, exposure, download; the stars of the previous frame are measured
  meanwhile).
- **Temperatures.** Focuser 26.7 °C and ambient 27.8 °C, 45 % humidity, dew point
  14.8 °C (PPBA) sampled into the catalog each minute; a saved frame carried
  `AMBTEMP`, `HUMIDITY`, `DEWPOINT` from NOCS and `FOCUSPOS`, `FOCUSTEM` from the
  driver. The EAF's own temperature compensation (`TEMPC_SWITCH`) is off and must
  stay off while NOCS focuses.

## Field test (2026-10-31, lab rig outside)

- The ZWO EAF on the 380 mm scope has ~600–700 steps of backlash. With the default
  overshoot (one step of the sweep) every sweep began with a plateau of identical
  HFR over hundreds of steps and failed as a bad fit, "not turning" or "flat";
  overshoot 1000 with a step of 30–40 worked. Autofocus now recognises that plateau
  (at least 3 points at the start whose HFR changes less than a quarter as much per
  step as the points after them) and fails with its own reason, *backlash*,
  suggesting an overshoot of 1.5 × (plateau + one step); the Focus screen offers to
  keep it for the focuser.

## Tuning under the sky (first clear night)

1. Focus by hand in Live view until stars show; note the position.
2. Run autofocus with a step of 100–300 on the 380 mm scope (9 points, 2–3 s):
   the ends of the sweep should be clearly out of focus (about 2.5 times the best
   HFR). Take the step the result suggests and run again; save it (Remember).
3. Repeat three times without touching anything: the best positions should agree
   within a fraction of a step; note the spread.
4. Approach direction and overshoot: run once outward and once inward (Advanced);
   the difference between their best positions is the backlash to cover.
5. Note R² and the last frame's HFR against the first of each run, to set the
   thresholds (contrast 1.2, R² 0.8, worse 10 %) from real curves.
6. Through a passing cloud or with the cap on: the run must fail with its reason
   and go back to where it started.
7. Two filters (L and Ha) for the offsets the sequencer will need later.
