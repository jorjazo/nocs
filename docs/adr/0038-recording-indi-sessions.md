# 0038. Recording INDI sessions of hardware NOCS has not been tested with

Date: 2026-11-03 · Status: Proposed

## Context

NOCS has been tested on ZWO devices, a Pegasus PPBA and the INDI simulators. INDI
standardises property names, not behaviour: every driver has its own timing, state
conventions and failure modes, and most of the gotchas in `CLAUDE.md` came from
real devices doing something the simulators do not. Owning every device is not
possible; users who own one are the way to learn how its driver behaves.

`dev/tools/indi_record.py` already records what indiserver sends (definitions,
updates, messages; no BLOBs) from a connection of its own, and the tests replay
those recordings (`FakeClient.replay`, `dev/tools/fake_ppba.py`). Its raw XML has no
times, and the lab rig's recording, made with the devices already connected, holds
what the drivers *define*, not how they *answer*. A test of behaviour (a move
aborted half way, a park, a sync) needs the commands and the answers in order.
indiserver gives a listening connection both: it echoes every client's `new*Vector`
to the other clients interested in that device (`indiserver.cpp`; measured with
the simulators), in the order it passes them to the driver.

Users run nocsd, not a lab CLI, and there is no NOCS server to receive files. A
recording also carries data that identifies the user: the site's coordinates,
serial numbers (in their own properties and in `/dev/serial/by-id/…` paths), host
names and addresses, home directories.

## Decision

**What a recording holds.** For the devices chosen (or all of them): everything
indiserver sends about them to a connection of the recorder's own, which asks only
for those devices (`getProperties device=…`) and never enables BLOBs (a BLOB that
arrives anyway keeps its size and format, not its content). That includes every
client's commands to them: nocsd's, PHD2's guide pulses, a KStars on the side. The
recorder needs nothing from nocsd's own INDI client; a command does not say which
client sent it. Each message has its time since the start.

**Format** (version 1): a zip with `manifest.json` and `session.jsonl`, one line
per message: `{"t": seconds, "xml": "<…/>"}` (a command is a `new*Vector`). The
manifest has the NOCS version, the start (UTC), the duration and why it ended, the
user's note, the devices asked for and those recorded, each device's driver
(`DRIVER_INFO`: name, executable, version, interfaces), the INDI packages installed
where the recorder runs (nocsd's machine, which runs indiserver), the number of
messages, commands and bytes, and how many values of each kind were scrubbed. The old raw XML recordings in
`dev/recordings/` stay as they are and readable.

**Limits.** A recording stops by itself after 30 minutes or 20 MB of session, or
when indiserver closes its connection; the manifest says which. The session is
written by a thread, which also parses and scrubs it, never the event loop.

**Privacy: scrubbed while recording.** The unscrubbed session is never written:

- the site (`GEOGRAPHIC_COORD`): latitude and longitude rounded to 1° (~100 km),
  keeping the hemisphere, which drivers' behaviour depends on; elevation to 100 m;
- serial numbers (serial number properties, the serial part of
  `/dev/serial/by-id/` names) become `serial-1`, `serial-2`… wherever they appear
  later, messages included;
- IPv4 addresses become `192.0.2.1` (a documentation address), the machine's host
  name `host`, a network device's address (`DEVICE_ADDRESS`) `host.invalid`;
- home directories (`/home/<name>`) become `/home/user`.

Device names, driver versions, the time zone offset, the start time and the note
are kept. Scrubbing knows the standard properties, not every driver's own: the app
says plainly what a file contains before it is downloaded.

**Sending.** No upload service: the owner downloads the file and attaches it to a
GitHub issue, opened from a link prefilled with what is not sensitive (drivers and
versions, the NOCS version). The issue template asks for permission to publish the
recording in `dev/recordings/` (a public repository); without it, it serves only
the maintainer's own investigation and is not committed.

**Who.** Recording from nocsd is for the paired owner only (ADR 0014), one at a
time, from the developer screen (`#/dev`). The lab CLI uses the same code.

**Replay.** A fake indiserver in the tests serves a recording's definitions and
answers each recorded command with what followed it, so a device facade can be
tested against a driver NOCS has never run.

## Consequences

- Contract tests can cover a driver's behaviour, not only its properties; each
  recording from a user's rig becomes a test of hardware the lab does not have.
- The recorder is one more client of indiserver while it runs, without BLOBs; it
  also records commands from clients other than nocsd, which a replay must answer
  like any other.
- Rounded coordinates cannot reproduce a bug that depends on the exact site; the
  hemisphere, which changes how mounts home and flip, is kept.
- A driver's own property may still hold something identifying (a Wi-Fi name, a
  custom label): the manifest counts what was replaced, and the user decides what
  to share.
- Work in stages: the recorder and its format, nocsd's API and state, the `#/dev`
  panel with the issue template, then the replay and the first contract test.
