# Supported hardware

NOCS drives equipment through [INDI](https://indilib.org): anything with an INDI
driver in the image (`indi-bin` and `indi-3rdparty-drivers`, from the INDI project's
PPA) can be used. NOCS knows devices by what they do (camera, mount, focuser, filter
wheel, power box, weather sensor), not by brand.

## Tested

The developer's rig, on which every release is tried:

| Role | Device | INDI driver |
|---|---|---|
| Main camera | ZWO ASI2600MC Duo | `indi_asi_ccd` |
| Guide camera | ZWO ASI220MM Mini (built into the Duo) | `indi_asi_ccd` |
| Filter wheel | ZWO EFW | `indi_asi_wheel` |
| Focuser | ZWO EAF | `indi_asi_focuser` |
| Mount | ZWO AM5, ZWO AM7 | `indi_lx200am5` |
| Power box | Pegasus Pocket Powerbox Advance Gen2 | `indi_pegasus_ppba` |

Next: iOptron GEM45G, Canon DSLRs (gphoto). Reports of other devices, working or
not, are welcome: send the diagnostics bundle (see [troubleshooting](troubleshooting.md)).

## Known quirks

- **ZWO AM5/AM7** keep their own clock and site: NOCS sends them the site and the
  time whenever the mount connects, and refuses a go to until it has. Their
  altitude limits are off by default.
- **ZWO EAF** reports a larger travel than it accepts: NOCS uses the limit of its
  position setting.
- **ZWO EFW** does not say that it is turning: a filter change shows only as its job,
  2–3 s.

## The computer

- **Raspberry Pi 5** (4 or 8 GB), with an active cooler and a 5 V / 5 A supply. NOCS
  shows the CPU temperature and warns when the supply is too weak, when the CPU slows
  down and when memory or the system disk runs low.
- **Storage:** the microSD card works; a USB SSD is faster and lasts longer. USB
  drives formatted FAT, exFAT, NTFS, ext4, btrfs or XFS are mounted when plugged in.
- **Wi-Fi:** the Pi's own. A USB hub with its own power helps when the camera, the
  guide camera, the focuser, the filter wheel and the mount all hang off the Pi.
- **USB GPS receivers** that gpsd reads (most NMEA ones, e.g. u-blox) give the box
  its time and offer their position as the site.
- **A PC** with Ubuntu 26.04 works too: see [installing on a PC](pc-install.md).

## Plate solving

The image includes ASTAP with its D50 star database, which solves fields from 0.2°
to 6° high: with an APS-C sensor, focal lengths from about 150 mm to 4.5 m. Shorter
lenses need ASTAP's G05 or W08 database, which NOCS reports as missing when a field
needs it.
