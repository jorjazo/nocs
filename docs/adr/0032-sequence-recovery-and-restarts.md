# 0032. Sequences: recovery, safety and restarts

Date: 2026-11-01 · Status: Proposed

## Context

Design principle 3 says "never lose a night": clouds, a lost guide star or a cable
glitch must lead to recovery, not to an abort. ADR 0031 runs a sequence as one
job with a checkpoint; until now any failed step ended the session. Facts that
shape what to do instead:

- **What fails, and how it looks.** Drivers answer `Alert` or time out
  (`DeviceError`, `TimeoutError`); a role disappears while its driver is
  restarted (ADR 0030: nocsd restarts a hung indiserver itself). Clouds give
  frames with few or no stars, and autofocus fails with *no stars*. PHD2 loses
  its star (`StarLost`, `LostLock`), and a frame taken meanwhile is trailed.
  Autofocus fails its quality checks and puts the focuser back (ADR 0021).
  Storage fills up or a drive goes away.
- **The sequence's own frame of reference.** Conditions (until a time, until
  dawn) say when waiting is pointless; a pause or a stop asked by the user must
  still take effect while the sequence waits for the sky to clear.
- **A restart of nocsd** (a crash, the watchdog of ADR 0030, a power blip) loses
  the job but not the checkpoint. nocsd does not connect the profile by itself
  when it starts, and until a client reports its clock or the system time is
  trusted (ADR 0029) the mount refuses go to's.
- The maintainer decided (2026-10-31): a restarted nocsd resumes the run by
  itself; frames under clouds are kept and marked, not deleted.

## Decision

### Failure kinds and policies

- The rig behind the sequence turns every failure into a **kind**: `device`,
  `clouds`, `guiding`, `focus`, `solve`, `storage` or `other`.
- **Clouds** are recognised on light frames: fewer stars than a quarter of the
  median of the row's last good frames, or fewer than 3 with no good frame yet.
  Such a frame stays saved (its star count in the catalog tells it apart) but
  does not count; autofocus failing with *no stars* is clouds too.
- **A lost guide star** shows when PHD2 is not guiding at the end of a frame
  that started guided: the frame does not count, and the next attempt starts
  guiding again first.
- Each kind has a **policy**: retry the step up to `retries` times (`None`:
  as long as the containers' conditions hold), waiting `wait` seconds before
  each retry, then `skip` the step, `skip_target`, `pause` for the user, or
  `end` the session. Waiting goes through safe points: a stop, a pause or a
  condition that ends (dawn) takes effect during the wait.
- Defaults, which a sequence can override per kind:

  | Kind | Retries | Wait | Then |
  |---|---|---|---|
  | clouds | while the conditions hold | 300 s | end |
  | guiding | 3 | 10 s | end |
  | device | 2 | 60 s | end |
  | focus | 0 | — | skip (keep the focuser where autofocus put it back) |
  | solve | 1 | 0 | skip_target |
  | storage, other | 0 | — | end |

- A skipped autofocus counts as a run for the triggers, so the next try comes at
  the next reason, not before every frame.
- Every failure, retry and decision is an event.

### End of session

- *End* brings the rig to a **safe state**: guiding stopped, mount parked (or
  tracking off when it cannot park), camera warmed with its ramp, chosen
  outputs off. It runs on completion, when a policy ends the session, and on a
  stop that asks for it (the default).

### Restarts

- The checkpoint names its sequence. When nocsd starts and finds an unfinished
  run, it connects the active profile, waits up to 10 minutes for the roles the
  sequence uses and for a known time, and resumes the run (ADR 0031: *start*
  again, frames never repeated). After 3 restarts in the same run, or when the
  wait runs out, it runs only *end*.
- A definition changed since the checkpoint was written is not resumed: only
  *end* runs.

### Events

- The run and its events go to the catalog (`sessions`, `session_events`), so
  the session report (stage 5.15) can be built after the fact, across restarts;
  a frame's event names the frame's catalog id.

### Supervision

- A `device` failure waits for the role to be ready again before retrying, which
  covers ADR 0030's driver and indiserver restarts. Resetting a USB port or
  cycling a power output from a policy waits until nocs-system offers them.

## Consequences

- A passing cloud costs the frames taken while it passed and the waiting time,
  not the night; a run that keeps failing still ends parked and warm.
- Policies are per kind, not per instruction: simple to show and to edit in the
  builder, at the cost of finer control nobody has asked for yet.
- Clouds are judged from star counts, which needs the preview's analysis of
  every light frame; a frame whose preview was skipped counts as good.
- After a restart without a client or a trusted clock, the run waits and then
  only parks: unattended nights need NTP, a GPS, or a phone left connected.
- The thresholds (a quarter of the stars, 300 s, 10 minutes, 3 restarts) are
  first guesses to tune from real nights.
