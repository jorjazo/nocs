# Video: the Moon, the Sun and the planets

Planets, the Moon's craters and the Sun's details are small and boil in the
atmosphere. Lucky imaging takes thousands of very short frames and keeps the
sharpest: the Video tab records them, and a stacker on your computer (AutoStakkert!,
PIPP, Siril…) does the rest.

## What you need

- The main camera, with a driver that streams video (ZWO, QHY, Player One and most
  CMOS cameras do). Video records straight to the storage drive, as SER files.
- A fast drive. A small region at a high frame rate writes tens or hundreds of
  megabytes a second: a USB SSD keeps up where a microSD card or a slow stick drops
  frames. Each recording says how many frames it dropped, if any.
- On a FAT drive (most sticks out of the box), a file cannot reach 4 GB: NOCS stops
  a recording just before it. Formatting the drive as exFAT or ext4 lifts the limit.

## A recording, step by step

1. **Go to the target.** Open *Go to* over the image and search for it: the planets,
   the Moon and the Sun are listed while they are up. For the Sun, read
   [The Sun and the Moon](sun-and-moon.md) first: a solar filter over the front of
   the telescope, always.
2. **Start** the video. The image is shown as recorded, never stretched.
3. **Expose.** Short exposures (a few milliseconds) freeze the seeing; raise the gain
   until the target is bright enough. The histogram's top turns orange when pixels
   saturate, and the share saturated shows next to it: keep it at zero.
4. **Choose a region** just larger than the target (640 × 480 for Jupiter at a long
   focal length) and *Place it on the image* where the target is. A smaller region
   reads faster: a ZWO ASI2600 gives 125 frames a second at 640 × 480, 11 at full
   frame.
5. **Track** at the target's rate: *Lunar* for the Moon, *Solar* for the Sun.
6. **Focus** with the focuser's buttons over the image, watching *Sharpness*: it grows
   as focus improves, and *best* keeps the highest since you last changed the
   exposure, gain or region. Autofocus measures stars and is not offered here.
7. **Record** for some seconds or a number of frames. While it records, the mount,
   the focuser and the filter wheel stay still. Jupiter turns fast: keep its
   recordings within a minute or two.

Recordings are listed under the settings, newest first, with their frames, frame
rate and size. Download them from there (large files take a while over Wi-Fi), or
take the drive to your computer: they are in `NOCS/<night>/Video/<target>/`.

While Video streams, Explore, Sequences and Plan wait: they all use the main camera.
