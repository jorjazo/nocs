# 0030. Supervision of indiserver, drivers, PHD2 and nocsd

Date: 2026-10-31 · Status: Proposed

## Context

systemd restarts indiserver, PHD2 and nocsd when they exit (ADR 0011, ADR 0022),
but nothing notices a process that **hangs without exiting**: a driver blocked in
a vendor SDK call, an indiserver that stops forwarding, a PHD2 that stops
answering, or nocsd's own event loop stuck. ADR 0015 noted that a hung event loop
would not stop a slewing mount. Facts:

- nocsd's commands already complete on the driver's `Ok` and fail on `Alert`; an
  exposure has a known duration. Both give natural deadlines.
- A `getProperties` for one device makes indiserver ask that driver to define its
  properties again: an answer proves that indiserver and the driver both work.
  Asked regularly, it would also re-send every definition into the state.
- **Measured** (stage 6.9, simulators in a container, INDI 2.2.5): indiserver
  answers a `<pingRequest uid=…/>` itself with `<pingReply uid=…/>` within a
  millisecond, also while one of its drivers is stopped (`SIGSTOP`). A stopped
  driver answers nothing, and its device's `getProperties` stays unanswered,
  while the other driver and pings carry on, even with 2000 requests queued for
  the stopped one. A frozen indiserver (`docker pause`) answers no ping, yet the
  kernel still accepts new connections to it: connecting proves nothing.
- A camera stuck in its SDK often needs more than a driver restart: a USB reset,
  or cutting its power. ADR 0017 records which power box output feeds which
  device.
- systemd offers a watchdog for services (`WatchdogSec`, kept alive with
  `WATCHDOG=1` on the notify socket) and, for the whole system, the hardware
  watchdog (`RuntimeWatchdogSec`); the Pi 5 has one (`/dev/watchdog0`).
- Restarting things in the middle of a night must not make it worse: a slow
  driver is not a hung one, and an exposure in progress is lost by a restart.

## Decision

- **Detection, in nocsd:**
  - **indiserver:** a ping every 10 s on nocsd's connection; three unanswered in a
    row (10 s each) mean it is hung. The state shows it as not answering from the
    first miss.
  - **devices:** a command without `Ok` or `Alert` before its deadline, or an
    exposure not received 60 s after it should have ended, marks the device
    **unresponsive**; a probe of that device (its `CONNECTION` property) confirms
    it. A device that sends nothing for 15 s while a command of its waits is probed
    too, so a hung camera is noticed long before a long exposure's deadline (stage
    6.9c).
  - **PHD2:** a JSON-RPC call without an answer for 15 s.
  - The state shows each as `unresponsive` with the time it was noticed.
- **Recovery ladder**, one step at a time, each only if the previous one did not
  help:
  1. restart the driver through the FIFO and connect its roles again (ADR 0011);
  2. restart indiserver (nocs-system, `services`), after which every device
     reconnects and PHD2 connects again;
  3. reset the device's USB port (nocs-system, `usb`);
  4. power cycle the power box output that feeds the device (ADR 0017): off for
     5 s, then on.

  Steps 1 and 2 run automatically, with an event for each. Steps 3 and 4 run
  automatically only under a running sequence, as its recovery policy decides
  (phase 5); otherwise the app offers them. The job that was using the device
  fails with the reason.

  **For v0.1** (decided 2026-10-31): step 3 waits until after the release,
  because which USB port an INDI device sits on cannot be found reliably. Step 4
  is the `device` policy's escalation in a sequence (ADR 0032): its first retry
  follows a driver restart, its second a power cycle of the output that feeds the
  device. The mount is never power cycled automatically (it would lose its
  position and alignment); outside a sequence, the app offers the power cycle as
  an action.
- **nocsd's own watchdog:** its unit is `Type=notify` with `WatchdogSec=30`; a
  task on the event loop sends `WATCHDOG=1` every 10 s through the notify socket
  (standard library only). A loop stuck for 30 s gets nocsd killed and restarted,
  and on restart it stops a mount found moving with no pad (ADR 0015).
- **The hardware watchdog** is on in the appliance (`RuntimeWatchdogSec=30s`):
  a hung kernel reboots the Pi.

## Consequences

- A hung driver costs the exposure in progress and a reconnection, not the night.
- Thresholds are a trade-off: too short and slow drivers get restarted, too long
  and minutes are lost. They are settings, and the session report lists every
  recovery, so they can be tuned from real nights.
- A sequence must survive its devices reconnecting (phase 5).
- Power cycling a device is only possible when the profile says which output feeds
  it.
