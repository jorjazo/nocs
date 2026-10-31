# 0031. Sequences: model, persistence and who owns the devices

Date: 2026-10-31 · Status: Proposed

## Context

Phase 5 ends with an unattended night: a multi-filter sequence started at dusk,
refocused when the temperature or the filter changes, flipped at the meridian,
parked at dawn. Design §9.5 describes the model (containers, instructions,
conditions, triggers, recovery policies); this ADR fixes its shape, where it is
kept and how it uses the devices. Facts that shape it:

- **Jobs do not nest** (`nocs.jobs`). A job locks roles until it ends; services
  start jobs for their commands (`goto`, `select`, `expose`) and offer functions
  that run inside a job already holding the roles (`CaptureService.take`,
  `AutofocusService.run`, on phase 3's branch `MountService.slew` and
  `CenteringService.center`).
- **Reservations** hold roles without a job: the slew pad, and PHD2, which holds
  the guide camera while connected and the mount while it guides (ADR 0023).
- **Between two jobs anyone can take a role.** A sequence made of one job per step
  would let a tap in Live view slip in between a filter change and its exposure.
- **The user still needs the rig mid-session** now and then: to look at a frame,
  nudge the focus, check the framing. Design §6 asks for "pause the sequence and
  do it" rather than a flat refusal.
- **nocsd can restart mid-night** (a crash, the watchdog of ADR 0030, a power
  blip); the Pi's clock may be days off in the field (ADR 0015), so the time a
  sequence trusts is `nocs.clock`'s.
- Profiles are JSON files in the config directory, written atomically; the
  catalog (SQLite) keeps frames, temperatures and focus runs (ADR 0013, 0021).

## Decision

### Model

- A **sequence** has three **containers**: *start* (cool, unpark, connect
  guiding…), *targets* (one container per target) and *end* (park, warm, outputs
  off). *End* always runs: on completion, on a stop that asks for it, and after a
  failure.
- A **container** runs its children in order, `repeat` times (1 by default; no
  limit when a condition ends it), while all its **conditions** hold. A container
  may name a **target** (name, J2000 coordinates), which its instructions use: a
  slew goes there, frames carry its name.
- **Instructions** are the leaves. An *action* is one step (cool, warm, unpark,
  park, slew, select a filter, autofocus, guide on/off, switch outputs). An
  **exposure plan** is a list of rows (filter, exposure, count, and optionally
  gain, offset, binning) taken one frame at a time, either in **batches** (up to N
  frames of a row, then the next row with frames left; 5 by default) or **in
  turn** (each row to its end). Batches keep every filter going for a target that
  sets early.
- **Conditions** are checked before each child and between frames: *until a time*
  first; *until dawn* and *while the target is above an altitude* come with the
  night's sky (stage 5.9). When one fails, the container ends after the frame in
  progress.
- **Triggers** belong to a container and apply to everything inside it. They are
  checked at the same safe points, after a filter change and before each frame.
  The first is autofocus: when the filter differs from the last run's, the
  focuser's temperature moved by more than a threshold since the last run, the
  median HFR of the last frames of a filter grew by a fraction over the frames
  right after the last run, after a time, or after a number of frames. Any
  autofocus, from a trigger or an instruction, resets them. Dithering, the
  meridian flip and re-centring come later as further kinds (ADR 0033).
- Models are Pydantic, with a `kind` discriminator and a `version`; new kinds are
  added without breaking stored sequences.

### Persistence

- **Definitions** are JSON files, one per sequence, in `<config dir>/sequences/`,
  written atomically: they can be exported and backed up like profiles.
- **Progress** is a checkpoint in the data directory, written atomically at every
  safe point: the frames done per plan row, the batch in progress, the containers
  finished, the iteration of each repeated container, the triggers' memory (last
  autofocus time, filter and temperature, HFR baselines), and a digest of the
  definition.
- **Resuming** a checkpoint repeats actions and never frames: *start* runs again
  (cooling, unparking, guiding), finished containers of *targets* are skipped,
  plans go on from their counts, and the actions of unfinished containers run
  again (the slew and focus of the current target). A run caught in *end* goes
  straight back to it. A checkpoint whose digest does not match the definition is not
  resumed.
- **Events** (started, paused, a trigger fired, a step failed, ended) go to the
  catalog for the session report (stage 5.12), not to the checkpoint.

### Who owns the devices

- **One sequence runs at a time, as one job** that locks the main camera, filter
  wheel, focuser and mount from start to end. Its instructions call the services'
  in-job functions, never their job-starting commands. Every service follows the
  convention: the command is a job around the in-job function. Cooling and power
  outputs take no lock and are called directly.
- **Guiding under a sequence:** the sequence connects PHD2, which reserves the
  guide camera as usual. When the caller's job already holds the mount, guiding
  does not reserve it again; the sequence stops guiding before it slews.
- **Pausing** happens at a safe point: after the frame in progress, or at once,
  dropping that frame. A paused sequence **lends its locks back**
  (`JobManager.suspend`), so Live view, the mount sheet and the focus screen work.
  Resuming takes them again (`JobManager.resume`) or is refused, naming what holds
  them. A command refused because a sequence holds a role says so, and the app
  offers to pause the sequence and do it.
- Conditions and triggers read the time from `nocs.clock`.

## Consequences

- No step of a running sequence can be interrupted by another command, and the
  user can still take the rig for a moment without stopping the night.
- Services grow in-job functions (save a light frame with its target, select a
  filter, park, guide without a mount hold) and the job-starting commands become
  thin wrappers around them.
- A restart costs the frame in progress and a repeat of the current target's
  setup (slew, focus), not the night.
- The tree can express more than the first UI offers: templates build it, and the
  builder shows it read only (no tree editor in v0.1).
- Recovery policies, the meridian flip and the session report build on this model
  (ADR 0032, ADR 0033).
