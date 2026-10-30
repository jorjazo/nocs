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

## 8. Open UX questions

- Persistent "session running" indicator on non-session screens (banner vs.
  tab badge).
- How to expose the full sequence tree editor (advanced) without cluttering the
  template view.
- Image interaction on phones: pinch-zoom, star inspection, FITS header view.
- Spanish copy review: text lengths in Spanish are ~20–30 % longer; layouts must
  be checked with both languages.
