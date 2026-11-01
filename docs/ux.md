# NOCS — UX and Design System

Status: draft (Phase 1) · Last updated: 2026-10-27

This document captures the information architecture, the key screens and the
design tokens of the NOCS web client. Mockups live on a design canvas (private
to the maintainer for now); this file is the source of truth for the decisions
behind them.

## 1. Information architecture

Navigation follows the night, not the device tree.

| Tab | Purpose | Main screens |
|---|---|---|
| **Tonight** | Home. Night window, conditions, and a "get ready" checklist that leads to each setup flow | Tonight · Polar alignment · Autofocus (full-screen flows) |
| **Live** | Manual imaging: preview, exposure settings, loop, save | Live view |
| **Plan** | Choose a target and build what to do with it | Target (search + framing) · Sequence |
| **Session** | Watch and control what the server is running | Session monitor |
| **Rig** | Equipment profile, optical trains, devices | Rig · device details |

- Phone: bottom tab bar. Tablet / desktop: left navigation rail.
- Guided flows (first run, polar alignment, autofocus) open full screen with a
  close button and a step indicator, and return to where they were started.
- The checklist on **Tonight** is the primary path for new users:
  connect → polar align → focus → frame → sequence. Each step shows its last
  result, and the next pending step carries the single primary button.
- A running session is always reachable in one tap from any screen (the
  Session tab; a persistent status indicator to be designed).

## 2. Key screens (Phase 1 canvas)

| Screen | Notes |
|---|---|
| First run | Create owner passphrase, pair this device, take time and location from the phone. Shows the hotspot name. |
| Tonight | Astronomical night window, environment from the power box sensor, setup checklist. |
| Rig | Imaging and guiding trains with derived FOV and pixel scale; device list with status. |
| Polar alignment | Target view with the axis error, per-axis readouts with plain-language direction ("Raise", "Turn west"). |
| Autofocus | Live V-curve with fit, best position / HFR / stars / temperature, cancel restores the previous position. |
| Framing | Target search, sky view with camera frame and rotation, altitude tonight, "Go and center". |
| Live view | Preview with metrics overlay, histogram, filter selector, exposure parameters, loop / capture / save. |
| Sequence | Template: target, exposures per filter, behaviors during the night, end-of-session actions, time and disk estimates. |
| Session | Progress, current exposure countdown, HFR / guiding / sensor, guiding graph, event timeline, pause / stop. |
| Session (tablet) | Same content in two columns, with the latest frame large and a filmstrip of recent frames. |

## 3. Themes

Two themes, switchable from any screen. **Night** is not a filter over Dusk:
it is a separate red-only palette that keeps every element legible while
preserving dark adaptation.

| Token | Dusk (default) | Night |
|---|---|---|
| `bg` | `#0A0D13` | `#000000` |
| `surface` | `#121722` | `#0E0303` |
| `raised` | `#1A2130` | `#170505` |
| `line` | `#263044` | `#3A0B0B` |
| `text` | `#E7EAF0` | `#FF6A5C` |
| `muted` | `#98A2B6` | `#E0473B` |
| `accent` | `#7DB7FF` | `#FF6A5C` |
| `on-accent` | `#06101C` | `#000000` |
| `ok` | `#4FD1A5` | `#E0473B` |
| `warning` | `#F5B04C` | `#FF8A7A` |
| `error` | `#FF6B5E` | `#FFB0A6` |
| `guide-ra` | `#7DB7FF` | `#FF6A5C` |
| `guide-dec` | `#F5A04C` | `#B8382E` (dotted) |

Rules:

- Text and muted text meet 4.5:1 on `surface` in both themes.
- Status is never color alone: chips always carry a word, and status dots differ
  in shape (circle / square / diamond) where it matters.
- Series in charts differ in lightness and line style, not only hue (RA solid,
  Dec dotted).
- Night mode must also dim the image previews (red-mapped, never white stars).

## 4. Typography

- **IBM Plex Sans** for interface text; **IBM Plex Mono** for every live number
  so digits do not shift as they update.

| Style | Size / line | Weight |
|---|---|---|
| Display | 32 / 38 | 600 |
| Title | 22 / 28 | 600 |
| Heading | 17 / 24 | 600 |
| Body | 15 / 22 | 400 |
| Label | 13 / 18 | 500 |
| Caption | 12 / 16 | 400–500 |
| Readout (mono) | 28 / 32, 20 / 26 | 500 |
| Data (mono) | 15 / 22, 13 / 18 | 400 |

## 5. Space, shape and touch

- 4 px grid: 4, 8, 12, 16, 24, 32, 48. Phone screen margins 20 px.
- Radii: tiles 10, buttons 12, cards 16, chips and toggles fully rounded.
- Primary actions 48–52 px tall; no touch target under 44 × 44 px.
- No hover-only affordances. One primary (accent) button per screen.

## 6. Components (initial set)

Buttons (primary, secondary, text, danger) · status chips · readout tiles ·
segmented control (filters, tabs) · toggle · progress bar and ring · device
list row · bottom tab bar / navigation rail · stepper (frame count) ·
full-screen flow header with step indicator · charts (V-curve, guiding,
altitude, histogram).

Icons: 24 px, 1.8 px stroke, round caps and joins, drawn in-house.

## 7. Implementation notes (stage 2.6)

- Screen headers on phones: title and the theme button on the first line, the
  screen's own controls (status chip, profile picker) on the next. Spanish titles
  and chips do not fit side by side at 375 px. Wide screens use one line and the
  navigation rail carries the theme button.
- Status chips tint their background with the status color (14 % in Dusk, 6 % in
  Night, where `ok` equals `muted` and a stronger tint drops below 4.5:1).
- Destructive actions (unpair, revoke) ask for a second tap instead of a browser
  dialog, which would flash white in Night mode.
- Spanish tab names: Esta noche · En vivo · Plan · Sesión · Equipo.
- First run asks for this device's name instead of a rig name, and leaves the
  phone's time and location to the mount stage (no API yet; geolocation needs a
  secure context, ADR 0014). The hotspot name waits for nocs-system.

Live view (stage 2.7):

- The shutter is the screen's one primary action: it takes a frame, and while
  the camera is busy it stops the job, with the exposure's progress on its ring.
  Loop and Save are toggles on either side; Save decides before the frame
  whether it is kept (only the main camera saves). Saving a preview after the
  fact needs server support (phase 2 plan, pending).
- On phones the actions and their errors stay docked above the tab bar while the
  settings scroll; wide screens put the preview on the left and the controls in
  a column on the right.
- The preview is drawn on a canvas. In Night mode the client maps its luminance
  to the red channel only (green and blue are zero), so no star is ever white.
- Pinch or wheel to zoom, drag to pan, double tap to switch between fitting the
  frame and its pixels at full size; the zoom is kept for new frames of the same
  size (focusing). Enlarging the preview is done in the page, not with the
  Fullscreen API, which iPhones do not offer.
- Over the image, the top label is the camera as it is now (device, sensor
  temperature, current filter); the bottom row describes the preview (HFR,
  stars, exposure) and the job status.
- The histogram's 256 bins cover where the data is (0.5 % to 99.5 % with a 30 %
  margin each side, whole quantization steps wide), not the whole 16-bit range,
  where a sky fills one or two bins; dotted lines and labels give the darkest
  and brightest values, so clipping still shows when it lies outside.
- Settings are kept by the server, so every client shows the same, and are
  locked while the camera runs a job. INDI keeps no exposure time, so the server
  keeps the last one set or used. Only the save choice and the camera shown are
  kept per device in the browser.
- Lights of the main camera show the target above the settings: its name and
  the folder its frames go to (`Light/<target>/`, cleaned as on the drive). Tapping
  it opens a sheet with the name, the targets of recent nights while it is empty
  and catalog objects as it is typed; Clear goes back to `Untitled`.
- The guide camera (stage 2.11) shares the screen through the camera switch. Its
  frames are only previews: no Save, no filter, no frame type (PHD2 keeps its own
  darks). A camera that reports its temperature read-only, like the ASI220MM,
  shows "None" on the cooler tile.

Power box (stage 2.10):

- The power box opens as a sheet from its row in Rig: input voltage, current
  and power, then each output with what the profile says it feeds, then the
  dew heaters. Switching an output off and changing the adjustable voltage take
  a second tap; when the server refuses because what the output feeds is busy,
  its reason shows with a "switch off anyway" choice that takes a second tap too.
- A new voltage is picked first and applied with its own button, with a reminder
  to check what is plugged in. Dew heaters are set by hand only with auto-dew
  off.
- Tonight shows the conditions from the weather role (temperature, humidity,
  dew point and the margin to it, in the warning color under 3 °C) above the
  rest of the screen, which arrives in phase 3.

Focuser, filter wheel and profile editor (stage 2.8):

- Live view puts the focuser under the filters: its position and temperature,
  and in / out buttons by the chosen step, so focusing by hand happens next to
  the preview while a loop runs. Tapping the position opens the focuser's sheet
  (step, go to a position, stop), which Rig opens too from the focuser's row.
- A main camera exposure locks the filter wheel and the focuser (a change would
  spoil the frame); a loop locks only the camera.
- Filter names belong to each physical wheel, not to a profile (ADR 0016). The
  wheel's sheet (Rig → the wheel, or the banner Live view shows for a wheel NOCS
  has not seen) lists one row per slot: tap a slot, then a common name (L, R,
  G, B, Ha, OIII, SII, Empty), which fills it and moves to the next slot; any
  name can be typed. "Move here" brings a slot into place to check by eye
  which filter it holds. The common names come first so that every wheel names
  a filter the same way.
- The profile editor (Rig → Edit profile / New profile, `#/rig/profile/<id>`)
  edits one role per row: driver from the rig's INDI catalog (the role's own
  catalog groups first), device name with the devices that driver runs now as
  suggestions, serial port from `/dev/serial/by-id/`; then both trains' optics
  and the site. Changes to a connected profile apply when it is next connected.

Guiding (stage 4.6):

- Guiding opens as a full-screen flow (`#/guiding`) from a link under the mount in
  Live view, which reads "Guiding · 0.42″" while PHD2 guides. It shows PHD2's
  state and whether it runs the profile's settings, the graph (RA solid in
  `guide-ra`, Dec dashed in `guide-dec`; dithers as dotted lines, lost frames as
  rings, settling steps paler; ″ or px), the RMS of the last 100 steady steps,
  SNR and HFD, the calibration, and the actions that fit: connect or loop, start
  guiding (calibrating first, or again on request), dither now, stop, disconnect.
- While PHD2 holds the guide camera, Live view shows its frames with a note, and
  its own shutter, loop and settings are off. While PHD2 calibrates or guides,
  the mount sheet says the mount waits and offers "Stop guiding"; the pad shows
  why it is off.
- Live view takes a series of the main camera (frames stepper) and dithers every
  n frames; the status says which frame of the series runs.
- The profile editor says when the guide camera looks through the imaging
  optics (an OAG or the Duo's sensor); the guiding train's fields go away then.

Mount (stage 2.9):

- The mount opens as a sheet from its row in Rig and from its readout in Live
  view: J2000 position, then JNow, alt/az and pier side; the slew pad; go to
  (J2000, typed as `00 42 44` / `+41 16 09` or decimals, or the zenith for a flat
  panel); tracking and its rate; park, unpark and home; the site and time the
  mount was given; the limits it keeps (read only). Stop, which aborts
  everything, sits under the pad and is always there, disabled while nothing
  moves; a running go to, park or home shows its progress under it.
- Nothing above the pad's arrows may appear, disappear or change height while
  they are held, or the arrow would slide out from under the finger: lines the
  mount reports only at times (alt/az, pier side) keep their place, blank.
- The slew pad moves the mount only while an arrow is held, two at once for a
  diagonal, at a speed picked from the driver's rates. The client repeats what
  it holds every 0.25 s and lets go when the finger lifts, the page goes to the
  background or the window loses focus; the server stops the mount after 1 s
  without a message (ADR 0015). After a stop NOCS made, the pad says so and
  waits for the arrows to be let go. Arrow keys work on a keyboard. East is on
  the left, as on a sky chart. Live view carries the pad folded under the
  focuser, for framing while a loop runs. Opened there, it docks above the
  shutter, compact, with the speed beside the arrows, while the preview stays
  pinned at the top with the frame's centre marked: the star is in sight while
  it moves.
- Speeds show the driver's labels, not its names (the AM5 calls 1440x `10x`):
  up to four as a segmented control, more with slower / faster buttons. The
  speed is sent at every start of a motion, since a driver may show one it
  never gave the mount.
- Park and home take a second tap; go to and zenith do not. A go to below the
  horizon is refused with a "Go anyway" that takes a second tap.
- Every time the state channel opens, the owner's device reports its clock.
  When the Pi's is more than 5 s off, a banner on every screen says by how much
  and that NOCS uses this device's time for frames and the mount.

Autofocus (stage 5.5):

- Autofocus is a full-screen flow at `#/focus`, without the tabs: a close button
  that returns to the screen that opened it, three steps (settings, sweep,
  result) as a bar under the title. Live view's focuser and the focuser's sheet
  open it; Tonight's checklist will once phase 3 builds Tonight.
- Settings show where the focuser is, its and the ambient temperature, the filter,
  and the last run with how much the focuser's temperature changed since. Step,
  points and exposure come from the imaging train's sweep in the profile and are
  saved back there when "Remember for this rig" is on (under Advanced, with frames
  per point and the focuser's backlash: approach direction and overshoot).
- While it runs: the V-curve (points as they are measured; rings on the axis for
  points without enough stars; where the focuser is now, dotted), readouts (best
  so far, HFR, stars, focuser temperature), the phase and a progress bar, and
  Cancel, which says that the focuser goes back to where it started. Any client
  that opens the screen follows a run that is going on.
- The result shows the fitted curve with the best focus dashed, HFR before and
  after and R², and when the fit suggests a step more than 15 % different, offers
  to keep it for next time. A failure names its cause and the next step for each
  quality check (no stars, too few stars, a curve that never turns, a bad fit, a
  worse last frame) and where the focuser went back to.
- Live view reports only its own exposures and loops as failed; a failed
  autofocus is reported on its own screen.

Plate solve (stage 3.2):

- Live view puts "Plate solve" under the mount (main camera only): Solve, and
  Solve and sync. Both take a frame with the camera's exposure; while the job
  runs the shutter shows its progress and stops it, and the status chip says
  Solving once the frame is in. A disabled button always comes with its reason
  (ASTAP missing, no star database for the field, no mount, parked, not tracking).
- The result card shows the centre (J2000), the angle of the top of the frame
  east of north (a bare angle until the framing assistant says which way to turn
  the camera, ADR 0018), the scale and field, the offset from where the mount
  pointed (total, then east/west and north/south), and when the frame was taken.
  After a plain solve, "Sync the mount" syncs to it; NOCS refuses when the mount
  has moved since the frame. A synced solution shows a chip instead.
- A failed solve is explained in the panel by its reason (not enough stars, no
  solution, no database…), not in the dock's generic banner.

Centre (stage 3.3):

- The mount's sheet puts "Go and centre" between Go and Zenith, for the same
  J2000 fields. It goes to the target, then takes frames with the main camera's
  exposure and corrects the mount until the frame's centre is within 1′ of the
  target, at most 5 frames: by syncing the mount to each frame, or for later
  callers (after a meridian flip) by aiming off by what the frame missed. A
  disabled button comes with its reason (no ASTAP, no main camera, camera busy);
  a target below the horizon gets the same "Go anyway" as Go.
- While it runs, the line under Stop says what it does and which frame of how
  many (Slewing, Settling, Solving · 2 of 5), and Stop cancels it.
- A centring card, in the sheet and in Live view under Plate solve, shows the
  target, the tolerance and how it corrects, then every frame: how far it landed
  from the target (total, east/west and north/south), "synced", or why it did
  not solve. Its chip says Centred, Not centred or Cancelled; a run that ran out
  of frames says how far it still was and what to check. The card stays with the
  latest run until the next one.

## 8. Open UX questions

- Persistent "session running" indicator on non-session screens (banner vs.
  tab badge).
- How to expose the full sequence tree editor (advanced) without cluttering the
  template view.
- Image interaction on phones: star inspection, FITS header view (pinch-zoom is
  in Live view since stage 2.7).
- Spanish copy review: text lengths in Spanish are ~20–30 % longer; layouts must
  be checked with both languages.

Appliance (phase 6):

- On the appliance, the first run continues after pairing with "Set up this box"
  (full screen, before anything else, while the access point keeps its default
  password): country, the access point's own password, and optionally a home
  network. The instructions for following the box (join the access point again,
  or switch to the home network, and open `http://<name>.local`) stay on screen
  after saving, since the phone may lose the box for a moment.
- Rig gains "This computer" (health, name, restart, shut down, INDI and PHD2
  restarts, diagnostics) and "Network" (where the box is, known networks, joining
  one, the access point, the mode); USB drives with Eject sit under Storage.
