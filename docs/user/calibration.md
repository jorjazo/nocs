# Calibration frames

Darks, flats and bias make the lights of a night cleaner when you stack them. NOCS
knows which ones a night's lights need, finds those you already have (from any
night: darks and bias for 180 days, flats from the same night or the same camera
rotation) and takes the missing ones.

Open **Session**, choose the night, and look at **Calibration** below its frames:
one row per group of lights (filter, exposure, sensor temperature, gain), with its
darks, its flats and the bias the flats need. Green: complete (20 darks, 20 flats,
50 bias). Amber: short, or missing.

## Darks and bias

**Take darks and bias…** takes them as a sequence you can leave running, for example
the morning after, with the telescope or the camera covered: no light may reach the
sensor. It cools the camera to each temperature, takes the bias, then the darks, and
warms the camera at the end if you ask.

The sheet lists the **lights to calibrate**: one switch per group of lights that
share their darks (exposure, temperature, gain, offset, binning; any filter). Each
says how many lights it has, their filters and targets, and the darks and bias it
would take, or "covered" when the library already has them. Only the groups that
are on are taken, and so are only their bias. Two kinds of group start off, with the
reason under them:

- **Few lights** (fewer than 5): test frames, such as the exposures you tried while
  framing or focusing.
- **Taken warm**: more than 5 °C above the camera's coldest group of 5 lights or
  more, usually lights taken while the camera was still cooling. A camera without
  cooling keeps all its groups on.

Turn a group on or off and the sheet says again how many frames that is and about
how long it takes (cooling not included). Start asks a second tap, "It is covered:
start", and the Session tab shows it like any other sequence.

## Flats

**Take flats…** opens the flats wizard: a panel (or a white screen) or the twilight
sky, the night's filters with their focuser positions, and how many flats each. The
flats keep the lights' gain, offset and binning, and need their own bias: take the
darks and bias too.

## Downloading

**Download with calibration** gives the night's zip with the matching darks, flats
and bias of other nights added, ready for your stacking program.
