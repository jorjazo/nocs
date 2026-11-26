# NOCS — UX and Design System

Status: draft (Phase 1) · Last updated: 2026-11-16

This document captures the information architecture, the key screens and the
design tokens of the NOCS web client. Mockups live on a design canvas (private
to the maintainer for now); this file is the source of truth for the decisions
behind them.

## 1. Information architecture

Navigation follows the night, not the device tree.

| Tab | Purpose | Main screens |
|---|---|---|
| **Tonight** | Home: the night and how the rig stands now. A "get ready" checklist that leads to each setup flow, the night window, where the mount points, the weather, the actuators, the location and time, the host (ADR 0053) | Tonight · Polar alignment · Autofocus (full-screen flows) |
| **Explore** | Try the sky tonight: the image, its histogram and status, the tools over it (guiding, focus, go to), loop, capture, save what is on screen (ADR 0054) | Explore |
| **Sequences** | Run groups of frames of what the camera has framed (lights per filter, darks, bias, flats), with the meridian flip and the night's rules; the same base as Explore, with the sequence's widget instead of go to. Explore, Sequences and Plan exclude each other | Sequences · Configure the sequence |
| **Visitors** | The night's image for people watching: the stack or the last capture, what it is of, how it was taken, the weather, a full-size JPEG to keep. The only view of a device that is not paired when the owner lets others watch | Visitors |
| **Plan** | Targets over one night or many, in priority, each with its lines of lights; the run takes the first that is up with frames left. The same base as Explore, with the plan's widget instead of go to | Plan · its targets · add a target · a target's page (search, framing, lines) |
| **Video** | Lucky imaging of the Moon, the Sun and the planets: the main camera's video live, a region read out for speed, SER recordings straight to the storage drive. The same base as Explore, with focus by hand on a sharpness number and go to (planets included) | Video |
| **Session** | The night's frames, their calibration and downloads, past sessions and their reports | Session · report |
| **Rig** | Equipment profile, optical trains, devices, the site, the box, settings | Rig · device details |

- Phone: bottom tab bar. Tablet / desktop: left navigation rail.
- Guided flows (first run, polar alignment, autofocus) open full screen with a
  close button and a step indicator, and return to where they were started.
- The checklist on **Tonight** is the primary path for new users:
  connect → focus → polar align (ADR 0053; framing and guiding belong to the target
  and sequence views). Each step shows its last
  result, and the next step carries the single primary button: the first one not
  done that can run. A step that cannot run yet shows what blocks it (the site, the
  plate solver, a device not ready, a parked mount, PHD2) with a link to where it is
  fixed, and has no button (ADR 0041).
- A running sequence or plan is always reachable in one tap from any screen (its
  tab, with a dot), and a sequence's prompts to ready the rig show on any screen.
- Explore, Sequences, Plan and Video exclude each other: while Explore loops or
  takes frames, while Video streams, or while a sequence or the plan is active
  (running, paused, or waiting on the user), the others' tabs are dimmed and going
  to them leads to the one that works. The server refuses Explore's and Video's
  frames during a run, and the camera's lock refuses the rest; the plan runs as a
  sequence, so only one of the two runs at a time.

## 2. Key screens (Phase 1 canvas)

| Screen | Notes |
|---|---|
| First run | Create owner passphrase, pair this device, take time and location from the phone. Shows the hotspot name. |
| Tonight | Setup checklist (first while a step is left), astronomical night window and the darkness left, where the mount points, the weather and its forecast, actuators, location and time, host; each a card that opens and closes. |
| Rig | The profile and its connection on top; below, collapsible sections in groups: imaging and guiding trains with derived FOV and pixel scale, devices with status; the saved sites and the active one; the box; settings (§7, "Rig"). |
| Polar alignment | Target view with the axis error, per-axis readouts with plain-language direction ("Raise", "Turn west"). |
| Autofocus | Live V-curve with fit, best position / HFR / stars / temperature, cancel restores the previous position. |
| Plan | Explore's base with the plan's widget at the right (the run's state, the target it takes and its lines, the targets in priority with their frames, recent events, the way to the targets), a panel with what the plan does at its start, around its targets and when it ends by itself, last frame or stack, start / pause / resume / stop. |
| The plan's targets | In priority, each with its lines, frames over every night, time left and how it does tonight; up and down, Add a target. |
| A target's page | Search (or coordinates, or one of my frames), the object, its lines, its altitude tonight, the framing chart with camera frame and rotation, "Go and center", remove, start its frames again. |
| Explore | The image edge to edge with a status bar and a folding histogram under it, guiding, focus and go to over it, and a panel of actions at its side (a sheet when upright): stack, filter, exposure, loop / capture, save / solve / download what is on screen (ADR 0054). |
| Sequences | Explore's base (image, histogram, status bar, guiding and focus over it) with the sequence's widget at the right (state, groups and their frames, the frame in progress, recent events, the way to configure it), a panel with what it does around its groups, last frame or group stack, start / pause / resume / stop. |
| Video | Explore's base: the live video edge to edge (linear, as recorded) with its histogram (the clipped top in the warning tone, the share saturated said) and a status bar (size, depth, exposure, fps, sharpness); the focuser over it by hand, with the sharpness and the best since the image last changed, no autofocus; go to at the right (the Sun, the Moon and the planets too; a planet has only "Go"). The panel: exposure in ms, gain, depth (8 or 16 bits, when the camera records both), the region (full or a size, placed by tapping the image), filter, tracking rate, the recording's length in seconds or frames with its size, then the recordings (download, delete, frames dropped). Dock: Start/Stop the video, Record. A recording keeps the mount, the focuser and the wheel still. |
| Configure the sequence | The saved sequences, the name, the groups in order (kind, filter, exposure, frames, settings), the calibration still missing, where the run will ask to ready the rig, estimates, the steps. |
| Session | The night's frames and their calibration, the past sessions; a banner leads to a running sequence. |

## 3. Themes

Two themes, switchable from any screen. **Dusk** is warm black with a brass
accent; color beyond the accent marks a state or a chart series. **Night** is not a filter over Dusk:
it is a separate red-only palette that keeps every element legible while
preserving dark adaptation.

| Token | Dusk (default) | Night |
|---|---|---|
| `bg` | `#0D0B08` | `#000000` |
| `surface` | `#16130E` | `#0E0303` |
| `raised` | `#201B14` | `#170505` |
| `line` | `#352D21` | `#3A0B0B` |
| `text` | `#EFE6D6` | `#FF6A5C` |
| `muted` | `#A8997F` | `#E0473B` |
| `accent` | `#D9AD62` | `#FF6A5C` |
| `on-accent` | `#140F07` | `#000000` |
| `ok` | `#9CC98A` | `#E0473B` |
| `warning` | `#F3D35C` | `#FF8A7A` |
| `error` | `#F07A5C` | `#FFB0A6` |
| `guide-ra` | `#D9AD62` | `#FF6A5C` |
| `guide-dec` | `#8FB8D8` | `#B8382E` (dotted) |
| `channel-red` | `#FF7B72` | `#FF6A5C` |
| `channel-green` | `#56D364` | `#E0473B` (dashed) |
| `channel-blue` | `#79B8FF` | `#B8382E` (dotted) |

Rules:

- Text and muted text meet 4.5:1 on `surface` in both themes.
- Status is never color alone: chips always carry a word, and status dots differ
  in shape: a circle when running or worth a look, a square when paused or a
  warning, a diamond for a problem. Brass and the warning's yellow are close.
- Series in charts differ in lightness and line style, not only hue (RA solid,
  Dec dotted).
- Night mode must also dim the image previews (red-mapped, never white stars).

## 4. Typography

- **Overpass** for interface text; **Overpass Mono** for every live number
  so digits do not shift as they update. Both are bundled (no internet in the field).

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
- Square corners everywhere: tiles, buttons, cards, chips, toggles. Only dots,
  spinners and the shutter stay round.
- Primary actions 48–52 px tall; no touch target under 44 × 44 px.
- No hover-only affordances. One primary (accent) button per screen.

Breakpoints and page width (`web/src/styles/tokens.css`; media queries cannot read
custom properties, so the breakpoints are written out where they are used):

| From | What changes |
|---|---|
| 420 px | Cards get their full side padding (small phones below) |
| 768 px | The navigation rail replaces the bottom tab bar; screen headers fit one line |
| 1000 px | Tablet: screens with a visual lay out in two columns (Session) |
| 1200 px | PC: "wide" pages grow from `--page-width` (760 px) to `--page-width-wide` (2400 px); Rig in two columns |
| 1600 px | Large screens: wide pages may use a third column (Session) |

Each screen's page is one of three widths (`web/src/lib/layout.ts`): **narrow**,
one readable column of at most 760 px (forms, lists, settings; most screens);
**wide**, the same below 1200 px and up to 2400 px from there, for screens laid
out in columns (Session, Rig); **full**, edge to edge without the page's margins
(Explore). A screen becomes wide only with a layout of its own for that width:
widening a single column only makes its lines longer.

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
- Status chips are a stripe of the status color at their left and the word in the
  text's color (muted when neutral). Banners, danger buttons and selected or
  pressed options tint their background with a color (14 % in Dusk, 6 % in Night,
  where muted text on a stronger tint drops below 4.5:1).
- Destructive actions (unpair, revoke) ask for a second tap instead of a browser
  dialog, which would flash white in Night mode.
- Spanish tab names: Esta noche · En vivo · Plan · Sesión · Equipo.
- First run asks for this device's name instead of a rig name, and leaves the
  phone's time and location to the mount stage (no API yet; geolocation needs a
  secure context, ADR 0014). The hotspot name waits for nocs-system.

Rig (2026-11-14):

- On top, always in view: the profile picker (in the header), the connection with
  its chip, Connect / Disconnect and Edit / New profile. Everything else is in
  sections, in four groups, each group a card under a small title:
  **Optics and devices** (Optical trains; Devices, with the INDI and PHD2 services and
  their restarts; without a profile, only the services), **Site** (Saved sites),
  **The box** (Status; Storage, with USB drives and file
  sharing; Network; Tailscale; Updates) and **Settings** (Access; This screen, the language; the
  INDI properties as a row that leads to their screen). The theme is not repeated
  there: its button is in every screen's header.
- Each section opens and closes on its own from its header (a button with a chevron
  and `aria-expanded`); this browser keeps which are open (`prefs`), like the theme.
  On a first visit only Devices is open. Closed, a header says how the section stands
  in a line ("5/6 online", "Internal · 15 GB free of 17 GB", the active site), and a
  problem shows as a chip ("Problem", "Check") whether the section is open or not:
  nothing opens by itself. Closing hides rather than removes, so what is typed or
  running inside survives.
- `#/rig/<section>` opens that section and scrolls to it: Tonight's "choose a site"
  leads to `#/rig/site`, and the site editor goes back there.
- The Rig tab carries a dot when something on Rig needs a look (a red diamond for a problem,
  a yellow square for a warning: no active site among them) or, for the owner, when updates are
  worth installing: a new NOCS, security fixes or a restart still due, each with its
  chip on Updates. Plain system updates come every few days and do not light it, nor
  does a failed join of a network: nocs-system keeps the last one until the next, so
  Network says it in words and nothing more.
- Observers see only Visitors (below), not Rig; the state they get still leaves
  out where the box is and which networks it knows (ADR 0047): no site, a GPS fix
  without its position, and no network names.
- From 1200 px the groups sit in two columns: the rig and its site on the left, the
  box and settings on the right.

Explore (ADR 0054) replaced Live view: the notes on Live view below describe what
it was, and still hold where Explore kept the same piece (viewer, shutter, sheets).

- The image takes the screen's height: on a screen lying down the panel of actions
  is a column at its side (clamped 300–400 px) that scrolls with its actions at the
  foot; upright, the actions sit under the image and the rest of the panel is a
  sheet over it, opened from a handle above them.
- Under the image, a folding histogram and the status bar (one line, scrolling
  sideways). The histogram's "Stretch" spans where the data is, with the stretch's
  curve per channel; "Full" spans 0–65535. Both mark the stretch's black point
  (solid) and mid grey (dashed) per channel, in `channel-red`, `-green`, `-blue`
  (one `text` mark for mono).
- A single tap on the image (after the double tap's 320 ms) shows or hides
  everything over it; the eye button does the same and stays visible. The camera
  switch sits over the image.
- The browser keeps which panes are open per orientation (`nocs.explore.panes`), and
  whether the overlays show and the histogram's scale per device. Lying down the
  tools start open; upright folded, one open at a time and as wide as the image.
- Tools over the image are cards (`ToolCard`) that fold into
  their icon, with a dot in the tool's tone; they size to the image (container
  units). Guiding, at the top left: PHD2's state, RA, Dec and total RMS of its last
  100 steps (arcseconds, or guide pixels without the scale), Guide or Stop, and the
  guiding screen. The focuser, under it: its position (which opens its sheet, where
  the step is set), a speed of half, once or twice that step (`nocs.focusSpeed`), in
  and out, and Autofocus, which starts at once with the profile's sweep, and "The
  curve" to its screen.
- Go to, at the top right under the buttons: the mount's position and what it is
  doing, the slew pad (narrow: smaller arrows, the speed under them), and a search of
  what is above the horizon now (`GET /api/sky/search`: catalog objects, and the Sun
  and the Moon by their English or Spanish names). A match offers Go and Go and centre;
  for the Sun or the Moon, Go and centre runs the finder. While PHD2 guides, both stop
  it and guide again once there in the same job (`resume_guiding`), said under the
  buttons; at the Sun or the Moon guiding only stops. A go to refused below the horizon
  or near the Sun is asked about as on the target's page.
  Going somewhere sets the lights' target name. While the panel is open the image's
  centre is marked; while the mount moves the newest frame shows instead of the stack.
  The mount's sheet (park, tracking) is in Rig only.
- The panel keeps the live stack, filters, the number of frames (a short stack), the
  exposure's tiles and the cooler; Explore exposes lights only, saves nothing at the
  time and never dithers. Under the shutter's row: Loop, the shutter, **Save**, and
  smaller **Solve** and **Download**. Save keeps what is on screen: the live stack
  while it is shown, else the frame behind the preview (`POST
  /api/cameras/main_camera/save`, with the facts read as it arrived), named after the
  last go to or else the object at its solved centre (a solution of it is kept with
  it); the caption then says where it went until the image changes, and the camera's
  `saved` keeps Save off for a frame saved already. Solve solves the frame on screen and only tells where
  it points (the status bar); syncing is part of Go and centre. Download is the JPEG on
  screen (`NOCS_<camera>_<time>.jpg`); sharing waits for HTTPS on the box.

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

Session: the night's frames (phase 2 field test):

- Until the sequence monitor (phase 5) arrives above it, the Session tab lists
  the frames saved on a night: the night (a picker when there are several), its
  frame count, total exposure and size, then one row per type, target and filter,
  then the frames newest first with their time, stars, HFR and guiding RMS (lost
  guide frames in the warning color), 50 at a time.
- The night's zip is the screen's primary action and says its size before it
  starts (a night is several GB); each group and each frame has its own download.
  Downloads are plain links, so the phone's browser keeps and shows them.
- Tapping a group lists only its frames. A frame whose drive is not connected is
  dimmed, without a download, under a banner naming the drive.
- Only the owner's devices list frames.

Power box (stage 2.10):

- The power box opens as a sheet from its row in Rig: input voltage, current
  and power, then each output with what the profile says it feeds, then the
  dew heaters. Switching an output off and changing the adjustable voltage take
  a second tap; when the server refuses because what the output feeds is busy,
  its reason shows with a "switch off anyway" choice that takes a second tap too.
- A new voltage is picked first and applied with its own button, with a reminder
  to check what is plugged in. Dew heaters are set by hand only with auto-dew
  off.
- Tonight's Weather card shows the conditions from the weather role (temperature,
  humidity, dew point and the margin to it, in the warning color under 3 °C) and
  the device they come from, then the forecast (ADR 0051) hour by hour until the
  end of the dark window: clouds (and low, mid, high), rain (and its chance), wind
  (and gusts), humidity and temperature, with the provider and its age.

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
  suggestions, serial port from `/dev/serial/by-id/` ("Found when connecting" when
  empty) with **Detect** beside it for serial roles, which tries the ports and shows
  each try under the field (ADR 0048); then both trains' optics.
  Changes to a connected profile apply when it is next connected.
- A role's driver is one field (an ARIA combobox, `DriverField`) that shows the
  model chosen, with the driver's executable under it. Tapping it selects its text
  and lists the drivers right under it, in the page's flow (never clipped; on a
  phone the field scrolls to the top, above the keyboard), the current one marked
  and in sight; typing filters by model, maker or executable (models and makers
  that match first), and the first match is active, so Enter takes it. Arrows and
  Page Up/Down move, a tap or a click chooses, Escape or leaving the field keeps
  the choice it had; × empties the field to search again. Each option shows the
  model, then the maker and the executable. INDI's catalog entries that give a real
  model a simulator's driver (the iOptron SkyGuider Pro, a tracker) are left out:
  they would be a simulated mount under a real name.
- The site belongs to the box, not to a profile (ADR 0038). Rig lists the saved
  sites under the trains, each with its position, the active one marked and the
  others with "Use"; the owner opens one to edit it (`#/rig/site/<id>`: name,
  latitude, longitude and elevation, filled with "From the mount" from the
  connected mount's own site or "From the GPS" from a USB GPS's fix, each disabled
  with its reason when it has nothing to give and naming the saved site within
  500 m when there is one (ADR 0042), or from "Paste a location"; delete) or adds one (`#/rig/site/new`), made
  active as it is saved unless the owner turns that off. A GPS with a 3D fix offers, under the list, the saved site
  within 500 m when it is not the active one, or else to save its position as a
  new site. The server refuses another active site while a job holds the mount.
- "Paste a location" (the site editor and the first run's site) reads, as it is
  pasted or typed, a Google Maps link (the place's pin, `!3d…!4d…`, before the
  view's centre, `@lat,lon`), coordinates as Maps copies them (`-33.4372,
  -70.6506`, a `;` between them when the decimals use commas) or degrees, minutes
  and seconds with hemispheres (N/S, E/W, O for west), in either order when the
  letters say which is which or only one order is in range; from what Maps' Share
  gives (the place's name, then the link) it takes the link; it fills the latitude and longitude and says what it
  read, or why it could not. A short link (`maps.app.goo.gl`, `goo.gl/maps`) holds no
  position: the box expands it (`POST /api/sites/maps-link`, Google's short-link
  hosts only, no redirect followed beyond them), which needs the internet; without
  it, or for a link to a place by its name only, the note says to copy the
  coordinates or share a dropped pin. The latitude and longitude fields take
  degrees, minutes and seconds too. Elevation stays typed or taken from the mount
  or the GPS: no link carries it.

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
  worse last frame, a best focus missed twice) and where the focuser went back to.
  A run that reached its best focus only at a second approach, with twice the
  overshoot, says so and offers to keep that overshoot for the focuser (ADR 0043).
- Live view reports only its own exposures and loops as failed; a failed
  autofocus is reported on its own screen.

Focuser calibration (ADR 0044):

- A full-screen flow at `#/focus/calibrate`, like autofocus: start, measuring,
  result. The focuser's sheet (Rig and Live view) opens it with the calibration's
  state under the autofocus button ("Overshoot 1400, calibrated …", or not
  calibrated for this profile); so do autofocus's Advanced settings and a failed
  autofocus (*backlash*, *missed*). Tonight's focus step offers "Calibrate" instead
  of "Focus" while the focuser has no calibration for the active profile:
  calibrating focuses too.
- Start says what it measures and what it needs (stars, near focus, a few minutes,
  the mount does not move), the last calibration (backlash each way, overshoot,
  focus zone), and autofocus's step. A driver that compensates backlash itself
  is mentioned: the calibration turns that off without asking, and the result says
  so.
- While it runs: autofocus's V-curve while it focuses, then each reversal's lost
  steps and each round trip as they come, the phase and a progress bar, Cancel.
- The result: the backlash inward and outward (every measurement), the overshoot
  that autofocus now uses on this focuser, the smallest significant step, a step
  in microns and the focus zone in steps; a warning when the measurements of one
  way disagree (check the coupling) or the drawtube slipped; and autofocus's
  suggested step with "Use it for autofocus". A failure names its cause.

Plate solve (stage 3.2):

- Live view puts "Plate solve" under the mount (main camera only): Solve, and
  Solve and sync. Both take a frame of the profile's solving exposure (2 s unless
  the profile editor says otherwise: not the camera's, which may be a long
  light's, as on `v0.1.0rc2`'s night out); while the job
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
- "Solve this frame" (after the first field test) solves the frame behind the
  preview as it is, without another exposure, also while a loop runs: NOCS keeps
  that frame until a newer one replaces it. The mount's position is the one when
  the frame arrived, and "Sync the mount" still refuses once the mount has moved.
  Solve and sync keeps taking a fresh frame.

Centre (stage 3.3):

- The mount's sheet puts "Go and centre" between Go and Zenith, for the same
  J2000 fields. It goes to the target, then takes frames of the profile's solving
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

The Sun and the Moon (ADR 0049):

- The mount's sheet has a "Sun and Moon" group under tracking: the search radius
  (degrees), "Search from here" with what it means (bring it near with the arrows;
  for the Sun, the tube's shadow), and "Find the Moon" and "Find the Sun". A
  disabled pair says why (no main camera, camera busy, no focal length); while
  PHD2 guides, a line says guiding stops first.
- The Sun's warning is a sheet: never look, a full-aperture certified filter, the
  finder and guide scope capped, nobody at the eyepiece; then that it asks again
  tomorrow and that finding the Sun stops PHD2. "The filter is on" takes a second
  tap. It opens before finding the Sun the first time each day, and whenever a go
  to (Go, Go and centre, Zenith, a target's page) is refused near the Sun; once
  acknowledged, the refused action is sent again.
- A finder card shows the body, its chip (Searching · 12 of 129, Measuring the
  axes, Centring…, then Centred, Not found, Not centred or Cancelled), the frames
  and their exposure, how far the disc is from the centre, how far the mount
  pointed off, the tracking rate and whether the mount was synced. Not found is a
  run that failed before seeing the disc, Not centred one that failed after. Live
  view shows it while it runs, under the centring card; the frames are its previews.

Tonight and Plan:

- Tonight is the home screen: the night as one bar from
  sunset to sunrise (daylight and the three twilights lighter, the dark window
  black, a line at now, the Moon's time up under it) with sunset, the dark
  window and sunrise under it; the dark window's length (or how dark it gets when
  it never gets fully dark) and the Moon's phase, light and rise and set. Without
  an active site it says so and leads to Rig's Site section (`#/rig/site`).
- The get-ready checklist lists Connect, Focus (with a focuser) and Polar align
  (ADR 0053); each step says how it stands, and the first pending one carries the
  screen's primary button. Connect offers "Connect <profile>" for the selected
  profile besides Open Rig; Focus goes to the focuser's calibration while it has
  none.
- Tonight's cards open and close like Rig's sections, and closed they still say
  how they stand: the checklist how many steps are done, the night how much of the
  dark window is left, Pointing the object, its altitude and the guiding RMS, the
  weather the next hour's forecast (else the sensor's reading; a "Dew near" chip
  open or closed), the actuators the power drawn and the sensor's temperature, the
  location the site, the time and whether all matches, the host the CPU, the memory
  and the room for frames. The night starts open and the rest closed, and each
  browser keeps what its user opened or closed; the checklist instead goes first and
  open while a step is left, last and closed once all are done. Order: checklist,
  night, Pointing, Weather, Actuators, Location and time (the owner's only), Host.
- Pointing: the mount's altitude and azimuth and J2000 coordinates, what is there
  (one of tonight's objects, the plan's targets, the first in priority, when it is in
  the main camera's frame, else the Sun or the Moon,
  else the nearest catalog object, else nothing), its altitude through the night,
  and the guiding RMS (total, RA and Dec). Parked and no mount say so.
- Actuators, read only: the camera's cooler (sensor against target, power, ramp; a
  chip when it stays more than 1 °C off once the ramp had time), dew heaters (fixed
  or automatic), 12 V outputs, the input (a chip under 12.0 V, red under 11.5 V).
- Location and time: the active site, its position and time zone; the box's time
  and what keeps it; the mount's site against the active one and whether NOCS gave
  it the time; the GPS's fix. A "Check" chip and a link to the site when something
  is off.
- Host: CPU use, memory, room for frames and on the system disk, CPU temperature,
  fan, supply, and who is connected (paired devices by name, observers counted).
- Every time in the app is in the active site's time zone (ADR 0052).
- The night says how the dark window stands now: "Dark in 1 h 20 min, for
  7 h 20 min" before it, "5 h 28 min of darkness left · 3 h 30 min without the
  Moon" during it (the Moon only when over 10 % lit), "The dark window is over"
  after it.
- Adding a target (`#/plan/add`): Catalog · Coordinates · My frames. The search
  takes a designation or a name, in either language and without accents, with a few
  targets to start from when it is empty; each result says what it is (type,
  constellation, magnitude, size) and how long it is up in the dark tonight.
  Coordinates take J2000 right ascension and declination, decimal or sexagesimal,
  and a name. My frames lists a night's lights by target and filter; one is solved
  (the one with the most stars, with the scale its headers give) and its centre and
  angle make the target.
- A target's page (`#/plan/object/<catalog id>` to add one, `#/plan/new` from
  coordinates, `#/plan/target/<id>` for one of the plan's): its names and what it
  is (a name to edit when it is not from the catalog), its lines, its altitude
  through the night (twilight shaded, the site's horizon profile as ground under it,
  the plan's minimum dashed, the Moon dotted, now), the highest point, the best
  window and the distance to the Moon; the framing chart with the main camera's frame
  and a rotation slider (it starts at the target's, else at the last solved frame's);
  dragging the sky frames off the object, which the caption says with a way back.
  Add to the plan is the primary action on a new one (a banner says when the object
  is in the plan already); Go and centre and Go stay, and name Explore's lights after
  the target. On one of the plan's: Start its frames again and Remove, each with a
  second tap. While the plan runs, the mount is the plan's: Go waits.
- A target's lines are taken in order, each to its end: a filter (none without a
  wheel), an exposure, a count, gain and offset (empty: the camera's when it starts).
  Each line keeps its frames over every night (the server counts them; all frames
  kept count). A sheet edits one; Add a line takes the next filter of the wheel and
  the last line's settings.
- The framing chart (stage 3.7b) draws the last solved frame dashed where it
  landed, and under the rotation slider says how far to turn the camera from that
  frame's angle to the framing's, with "Use the camera's angle". "Survey image" (off
  by default, kept per device) puts DSS2 in colour under the chart: the phone
  itself fetches the survey's HiPS tiles and draws them in the chart's projection,
  from IRSA, ESA or CDS (mirrors of the same tiles; the one that worked last is
  asked first, for 20 h). Any view gets its whole image, at the screen's pixels,
  in a second or two; tiles are asked as the view moves (and a little past its
  edges), and the tiles already loaded stand in while the ones the new zoom needs
  come: coarser ones zooming in, finer ones zooming out. A mirror that fails a
  tile (5 s without it) is skipped for five minutes by every chart, across reloads,
  then asked again by itself; when none answers, NASA SkyView's DSS2 red covers the
  view's middle 5° at most (it is too slow for more), until the mirrors' tiles cover
  the view again. While loading, the caption names the service being asked, and
  then credits the mirror; without an image it says why, per service ("IRSA not
  answering · ESA not answering · CDS answered with an error · SkyView too slow for
  this view", "IRSA, ESA, CDS, and SkyView cannot be reached. No internet on this
  device?", "this device is offline"). In Night mode it is drawn in red only.

Sequences:

- Same layout as Explore (the shared `ImageScreen` and `ImageOverlay`): guiding and
  focus at the top left, the sequence's widget at the right where Explore has go
  to; they fold and keep Explore's per-device choices.
- A sequence is groups of frames of what the camera has framed: each group a kind
  (Light, Dark, Bias, Flat), a filter (lights and flats), an exposure (bias take the
  camera's shortest; flats find theirs from the last frame's level, or take a fixed
  one), frames, gain, offset, binning, and a temperature when cooling is per group.
  Groups are taken in their order, each to its last frame; the night's end (dawn,
  the minimum altitude) can cut the lights short, leaving later light groups with
  fewer frames or none. When the run starts it
  solves what is framed (or takes where the mount points) and names it after the
  last go to or the catalog object nearest it: the target of the flip, the centring
  and the altitude.
- Whenever the kind of frames changes between lights, darks and bias (covered) and
  flats (a panel), and before the first group when it is not lights, the run stops
  and asks: a dialog on any screen of the owner's devices ("Cover the telescope",
  "Put the flat panel on", "Uncover the telescope") with a vibration and a short
  tone where allowed, Ready (go on) and Stop; "Later" folds it and the view's dock
  keeps asking. Guiding stops before darks and flats. The rig is lent back while it
  asks, as in a pause.
- The panel: Last frame · Group stack (a group of lights' live stack, held on during
  a sequence whatever the Stack switch; a group of darks, bias or flats' master once
  the group ends), and what it does around its groups, as Explore's old builder:
  Autofocus, Centring, Guiding, Meridian flip, Dither, Night (lights
  only: dusk, dawn, minimum altitude), Cooling (off, one temperature for all, or per
  group), When finished. Read only while it runs. Changes are saved a moment after
  they are made; a line says the time, the frames and their size.
- The dock: Start sequence (off while Explore takes frames, saying so), then Pause
  (Pause now while pausing), Resume (or Ready while it asks) and Stop… (after this
  frame or now, each with the end or leaving the rig as it is).
- The widget: the state (Ready, Running, Waiting for you, Paused…, Completed), what
  is framed, each group with its frames done and a bar (the current one marked),
  the frame in progress with its countdown or what the run is doing, the time left
  and when it ends, the three latest events, and Configure the sequence.
- Configure the sequence (`#/sequence/edit`): the saved sequences when there are
  several (the one shown is the running one, else the one chosen last on this
  device), New sequence, the name, the groups (a sheet each; up and down to reorder),
  *Add missing calibration* (flats per filter, then the bias and darks its lights
  lack in the library and the sequence does not plan), the prompts the run will
  make, the estimates; Advanced: minutes past the meridian, the
  steps, delete.
- Each group of lights keeps its live stacks (`<night>/Stack/…`); each group of
  darks, bias or flats its master (`<night>/Master/`, flats by filter): the median in
  the sensor's own pixels, 16 bits, flats not bias-subtracted.

Plan:

- Same layout as Sequences (`ImageScreen`, `ImageOverlay`): guiding and focus at the
  top left, the plan's widget at the right where Explore has go to.
- The plan is the targets, in priority, each with its lines of lights, over one
  night or many. Its run takes the first target that is up (above the plan's minimum
  altitude and the site's horizon) with frames left; it centres it (or goes to it),
  guides when asked, focuses on the first one, and takes its lines in order. Every
  10 minutes, and whenever a line ends, it looks again: between two frames (never
  cutting one) it goes to a target that now comes first. A target that fails (a
  solve, say) or sets before a frame is left out 15 minutes while the others are
  taken (the events say until when). With none up it waits, until one rises or the
  night ends. Without a minimum altitude a target is still taken only above the
  horizon. A plan.json that cannot be read is moved aside, not overwritten.
- The panel: Last frame · Stack, the plan's targets and frames left (to the targets'
  page), then what it does: At the start (outputs switched on, such as dew heaters,
  shown when there is a power box), Autofocus, Centring, Guiding, Meridian flip,
  Dither, Night (dusk, dawn, minimum altitude), Cooling (off or one temperature),
  When it ends by itself. These stay as they are while it runs; its targets do not:
  a change to the target it takes (or removing it) counts before its next frame, the
  rest at the next look. Changes are saved a moment after they are made, and tried
  again while the box cannot be reached; Start saves them first.
- The dock: Start the plan (off while Explore or a sequence works, or with no frames
  left), then Pause (Pause now while pausing), Resume and Stop…: after this frame or
  now, always leaving the rig as it is. The end (park, warm, outputs off) runs only
  when the plan ends by itself: at dawn, or with every target done.
- The widget: the state, the target it takes with each line's frames (the current
  one marked), the frame in progress or what the run is doing, the targets in
  priority with their frames over every night, the time their frames still take, the
  three latest events, and the way to the targets.
- The plan's targets (`#/plan/edit`): each with its place, its lines, a bar of its
  frames, its exposure so far and what is left, "Taking now" and how it does tonight;
  up and down change its priority, a tap opens its page, Add a target finds another.

Visitors:

- `#/visits`: a tab for the owner, and the only screen of a device that is not paired
  while the owner lets others watch (Rig → Access): no tabs, whatever the address
  says, with the banner that offers to pair. Visitors reach it on the box's network at
  `nocs.local`; nothing is shared from it (no QR, no network name).
- Explore's base, without the tools over the image: the image fills the screen (a
  tap enlarges it), with the stack or the last capture, each visitor's choice (kept in
  the browser, as Explore's); before the first image, "Waiting for the first image".
- The panel: what the image is of, as Tonight's Pointing names it (one of tonight's
  objects, the Sun or the Moon, else the nearest catalog object) with what it is
  (type, constellation, magnitude, size); how it was taken (the stack: frames, total
  time, each exposure, gain, filter; the capture: exposure, gain, filter, when); the
  temperature and humidity outside (the sensor's, else the forecast's hour, said
  so); night mode, off until the visitor turns it on.
- The dock: Download the stack, or this capture: a full-size JPEG
  (`/api/visit/stack.jpg`, `/api/visit/frame.jpg`), stretched as on screen, rendered
  once per image (or stack and look) however many download it. The button says
  "Making the picture…" meanwhile (a few seconds for 26 MP), and why it could not be
  (not ready yet, watching turned off, the box out of reach), without paths. A
  frame replaced as it is asked for gives the newer one. No FITS, and no share button
  (sharing waits for HTTPS on the box): the gallery shares it.

Session report (stage 5.15):

- The Session tab lists the past sessions, newest first, each with its date and
  how it ended; one opens its report (`#/session/<id>`).
- The report: the name, date and profile; the window (start → end, length) and how
  it ended, with the error; totals (integration, frames, frames under clouds,
  failures and how many were recovered); a table per filter (frames, with those
  under clouds in brackets, integration, median HFR and guiding RMS); the HFR of
  each frame over the night with autofocus runs as dashed lines; the focuser's and
  the ambient temperature (solid and dashed); the autofocus runs with their
  position, HFR, filter and what triggered them; every event; Frames as CSV.

Calibration frames (ADR 0036):

- Under a night's groups, the Session tab shows its calibration: one row per group
  of lights (filter, exposure, sensor temperature, gain, binning) with chips for
  its darks, its flats and the bias the flats need: green with the count and the
  newest night when the set is complete (20 darks, 20 flats, 50 bias), yellow with
  "2/20" when short, yellow "Missing" when there is none. Matches come from any
  night (darks and bias for 180 days; flats the same night, or the same rotation).
- *Take darks and bias…* opens a sheet: a warning to cover the telescope or the
  camera; the lights to calibrate, one switch per group that shares its darks
  (exposure, temperature, gain, offset, binning; its lights, filters and targets,
  and the darks and bias it would take or "covered"), test frames (fewer than 5
  lights) and lights taken warm off by default with the reason; darks per
  exposure, bias, warm at the end; the frames and the time the choice takes,
  updated as it changes. Start asks a second tap ("It is covered: start"), builds
  the `calibration` sequence (groups that can be edited in Sequences) and starts it
  in Sequences, which asks first to cover the telescope. Sets it cannot take
  (another camera, a region of the sensor) are named in a banner.
- *Take flats…* opens the flats wizard (`#/flats/<night>`, full screen): Panel or
  Twilight sky with what each does; for the sky, the next dusk and dawn windows;
  the night's filters, each with its focuser position and a count (on for those
  missing flats); the level (50 % of full scale); Advanced: the shortest and
  longest exposure. Gain, offset and binning are the night's lights'. While it runs:
  the state, what it waits for (the twilight), and per filter the flats kept of the
  count, the latest exposure and level, and a bar; Cancel; then Take more or Done.
- *Download with calibration* is the night's zip with the matching frames of other
  nights added.

Live stacking (ADR 0040, after v1.0):

- Live view's main camera gets a *Stack frames as they arrive* switch under the
  histogram; it is the server's, so every client shows the same, and it covers
  sequences too. Off, it explains what it does in one line.
- On, a *Stack · Frame* choice (kept per device) says what the viewer shows; the
  stack replaces the frame and its histogram (but not while framing with the mount's
  pad: the newest frame shows where the mount points), and the status bar says *Stack*, its
  frames and its total exposure. Sequences offers the same choice (Last frame ·
  Group stack).
- Below: frames, total time, frames left out and frames that arrived while the
  worker was busy, in words; a chip with what calibrates the frames (darks and
  flats, darks, flats, hot pixels removed); the latest frame's outcome (how far it
  lay from the first, or why it was left out, in the warning color); what the
  calibration is made of (20 darks · flats without their bias: not used). Reasons
  are the client's words, not the server's English.
- *New stack*, *Save* and *Look*. A stack is saved by itself when it ends (New stack,
  the switch off, another setup) with two frames or more, and *Save* keeps it as it is
  now; the card then says where. The night's frames list a saved stack with a link
  to its picture beside the FITS. The look is a sheet of preset steps, not sliders (sky,
  black point, color, and keeping the camera's color balance), applied as each
  is tapped: the server re-renders the stack at once for every client. The sheet keeps
  its own copy while it is open (a second tap must not undo the first before the
  server answers), and shows its own errors.
- Observers see the stack in Visitors (an outreach night), not this card.

## 8. Open UX questions

- How to expose the full sequence tree editor (advanced) without cluttering the
  template view (v0.1 shows the tree read only under Advanced).
- Image interaction on phones: star inspection, FITS header view (pinch-zoom is
  in Explore, and Live view before it, since stage 2.7).
- Spanish copy review: text lengths in Spanish are ~20–30 % longer; layouts must
  be checked with both languages.
- Other screens on a PC: only Session has a wide layout so far. Plan (the target's
  framing chart beside its details), the session report (its charts) and Tonight
  could use one; Explore is already edge to edge (ADR 0054). Each needs its own layout for that width, not just a wider column.

Appliance (phase 6):

- On the appliance, the first run continues after pairing with "Set up this box"
  (full screen, before anything else, until nocs-system records it), in steps with
  a step indicator and Back/Next: the access point (country, its own password, and
  a warning to leave USB devices unplugged: USB 3 drowns out its 2.4 GHz Wi-Fi), a
  home network (optional), the box's name (where nocs-system may rename it), the
  site (optional, ADR 0042: a saved one, or a new one typed in or filled from a
  mount or GPS that happens to be connected; "a rough position is enough"), and a
  last step that shows what will happen. Nothing is sent before that last step,
  which saves the site first, so the phone loses the access point only once the
  instructions for following the box (join the access point again, or switch to the
  home network, and open `http://<name>.local`, pairing again after a new name) are
  on screen; they stay there after applying. A later step is one more entry in
  `lib/boxsetup.ts` and its own section of the screen.
- Rig gains "Status" (health, name, restart, shut down, diagnostics) and "Network"
  (where the box is, known networks, the mode; joining one and the access point open
  as sheets), in the box's group; INDI and PHD2 restarts sit under Devices, with their
  services' rows, and USB drives with Eject under Storage.
- Updates, a section of the box's group where nocs-system installs them (ADR 0025), are for a
  decision, not a dump of apt (rc2's field notes): NOCS first (installed version,
  the new one with a "New version" chip, or "Up to date"), then INDI and PHD2 as one
  line each (the version of `indi-bin`/`phd2` shortened to what people know, and how
  many packages INDI's update spans), then the system as one count ("180 updates,
  112 of them security"). Every package sits behind a disclosure ("All 187
  packages"), one row each (name, a Security mark, old → new), grouped as above.
  When it was last checked sits by the heading (a date when not today), with "Check
  now". Before Install, a short list says what installing does: NOCS restarts or
  keeps running, INDI and PHD2 keep their old version until restarted, a new kernel
  needs a restart of the box, and NOCS refuses while something runs (a banner says
  so when something does; a refusal offers "Install anyway"). After it: how many
  were installed, what is left (apt is asked again), and when Ubuntu asks for a
  restart, a banner with Restart. ASTAP is not an apt package and is not shown.
- Rig's "Tailscale", in the box's group, for the owner where Tailscale runs: on the
  tailnet, the box's address there (`http://<name>.<tailnet>.ts.net`, selectable), the
  tailnet and a line saying whose devices pair without the passphrase (a warning
  instead for a tagged box, which has no owner); off it, "Join a tailnet" where
  nocs-system may (the appliance), then the sign-in link as a plain link (a new tab)
  until Tailscale says the box is on, or waits for an admin's approval. The link
  comes only in the answer to the owner who asked (the state says only that a sign-in
  waits: whoever opens the link first gets the box), so another device or a reload
  shows "Show the sign-in link" instead; "Leave the tailnet" with a second tap. On a PC it only shows
  where the box is.
- Pairing on a tailnet: when Tailscale says the device is the owner's, the pairing
  screen says so under the device's name and offers "Pair with Tailscale" as the
  primary button, with the passphrase below it ("Or with the passphrase") as the
  secondary way. First run never offers it: the passphrase comes first.
- Rig's "File sharing" (ADR 0039), under Storage, where nocs-system runs the share: a
  switch ("Share frames with computers", saying it is read-only and open to anyone on
  the network); while on, a chip with the computers connected, how to open it from
  Windows (`\\<name>.local\Internal`), a Mac and Linux (`smb://<name>.local`) as
  selectable text (no clipboard over plain HTTP), the `nocs` / `nocs` login for
  Windows 11, the shared folders (Internal, then each USB drive by label) and a note
  that copying can slow saving on the microSD. On but not running shows a warning.
