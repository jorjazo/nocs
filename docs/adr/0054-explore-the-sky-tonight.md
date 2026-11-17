# 0054. Explore is for trying the sky tonight: the image first, its tools over it, and saving what is on screen

Date: 2026-11-17 · Status: Proposed

## Context

The maintainer is redefining every view so that each has one purpose that says what
belongs in it ("Experiencia NOCS"; Tonight was the first, ADR 0053). Explore replaces
Live view. Its purpose: explore the objects up tonight and experiment with the
framing, the exposure, the colours. Live view had grown into a column of everything
the main camera touches: dithering, frame types, the lights' folder, polar alignment,
the mount's sheet. Facts:

- **The server keeps the frame behind the main camera's preview** (`KeptFrame`), for
  "Solve this frame": saving it later needs no new exposure.
- **Loops already feed the live stack** (ADR 0040), so a short stack needs no saved
  frames.
- **The preview is stretched on the server** (a midtones transfer per channel) and
  its histogram spans only where the data is; neither the stretch nor the camera's
  whole scale reached the client.
- **The box is served over plain HTTP**: browsers offer the Web Share API only in a
  secure context, so a page cannot share an image; it can download one.
- **Screens are used lying down** where possible (the maintainer's wish): a browser
  cannot force the orientation, an installed app only on some systems.

## Decision

- **The route is `#/explore`, the tab "Explore"** ("Explorar"). The rest of the menu
  changes in a change of its own.
- **The image fills the screen.** Under it, a **status bar**: the camera and its
  temperature (and the target while cooling), what it is doing, the frame's size in
  pixels and its binning, stars, HFR and exposure (or the stack's frames and time),
  where it points when that frame was solved, and the time until the mount reaches
  the meridian at the site. Over the status bar a **histogram** that folds: "Stretch"
  spans the data with the stretch's curve over it, "Full" the whole 16-bit scale;
  both mark where the stretch turns each channel black and mid grey. The server adds
  `histogram_full`, `stretch`, `frame_width`, `frame_height` and `binning` to each
  preview. Viewer, status bar and histogram are pieces of their own, for the coming
  view for visitors.
- **Tools over the image**, each folding into its icon: guiding at the top left (RA,
  Dec and total RMS of PHD2's last 100 steps, start and stop, a link to the guiding
  screen), the focuser under it (a speed of half, one or two times the step set on
  this device, in and out, autofocus started at once with a link to its curve), and
  at the right a go to panel (the slew pad; a search of catalog objects above the
  horizon now, the Sun and the Moon among them; "Go" and "Go and centre", which for
  the Sun or the Moon runs their finder, ADR 0049). The camera switch sits over the
  image too. A tap on the image shows or hides all of it.
- **The panel of actions** keeps the rest: the live stack, filters, the exposure's
  settings, the cooler, the number of frames (for a short stack), loop and capture,
  and three buttons: **Save** stores what is on screen (the kept frame as a light, or
  the live stack), **Solve** solves the frame on screen and only says where it points
  (syncing is part of "Go and centre"), **Download** gives the JPEG on screen.
  Explore takes lights only and never dithers; frame types and dithering belong to
  sequences, polar alignment to Tonight, the mount's sheet to Rig.
- **A saved frame's name** is the object of the last go to; without one, the catalog
  object nearest the centre of that frame's solution, within its field; else none
  ("Untitled").
- **Lying down**, the panel is a column at the image's side and the tools start open;
  **upright**, the panel is a sheet over the image with its actions always showing,
  and the tools start folded. The browser keeps, per orientation, which panes are
  open, whether the tools show and the histogram's scale.

## Consequences

- Saving no longer happens before a frame: to keep a frame, look at it and save it.
  Series that save go through sequences.
- Sharing waits for HTTPS on the box; downloading works everywhere, and a phone shares
  the file from its gallery.
- The guiding figures are PHD2's last 100 steps, not those of the frame on screen.
- The name of the last go to stays until the next one: a frame framed by hand with the
  pad afterwards still gets it.
