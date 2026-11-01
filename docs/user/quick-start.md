# Quick start

From a new Raspberry Pi 5 to your first frames, controlled from a phone. No other
computer is needed at the telescope.

## What you need

- A **Raspberry Pi 5** (4 GB or 8 GB) with an active cooler.
- Its **official 27 W power supply**, or a supply that gives 5 V at 5 A. A weak
  supply is the most common cause of trouble: NOCS warns about it.
- A **microSD card** of 32 GB or more, or a **USB SSD** (faster, and it does not wear
  out like a card). NOCS saves frames to a USB drive when one is plugged in, and to
  the card otherwise.
- Optional: the Pi 5's **RTC battery**, so that the clock keeps time while the Pi is
  off, and a **USB GPS** receiver for the time and the site without a phone.
- Your equipment, with its INDI drivers: see [supported hardware](hardware.md).

## 1. Write the image

1. Download `nocs-<version>-pi5-arm64.img.xz` and its `.sha256` from the release
   page.
2. Open [Raspberry Pi Imager](https://www.raspberrypi.com/software/), choose
   **Raspberry Pi 5**, then **Use custom** and the `.img.xz` file, and your card or
   SSD.
3. Optional, under **Edit settings**: your home Wi-Fi (the box joins it whenever it
   is in range), a host name, and a public SSH key. NOCS does not need any of them.
4. Write. To boot from a USB SSD, write the SSD and take the microSD card out of the
   Pi.

## 2. First boot

Plug the equipment in and power the Pi on. The first boot takes one or two
minutes. Without a known network, the Pi then starts its own Wi-Fi:

| Network | `NOCS-xxxx` (the last four characters of the Pi's serial number) |
|---|---|
| Password | `nocs-setup` (you change it in a moment) |
| Address | <http://nocs.local>, or <http://10.42.0.1> |

Join it from your phone. The phone will warn that this network has no internet:
stay on it. Then open <http://nocs.local> in the browser.

If you gave Imager your home Wi-Fi, join that network instead and open
<http://nocs.local> there.

## 3. Set up

1. **Owner passphrase.** Name this phone and choose a passphrase of at least 8
   characters. It pairs this phone, which then stays signed in. You need the
   passphrase again only to pair another phone or computer.
2. **Set up this box.** Choose your country and a password of your own for the
   box's Wi-Fi. Optionally, give it your home Wi-Fi too. When you save, the box
   restarts its Wi-Fi with the new password (or joins your home network): follow it
   from the phone, as the screen says, and open <http://nocs.local> again.

## 4. Your equipment

On **Rig**:

1. **New profile**: pick the driver of each device (main camera, guide camera,
   mount, focuser, filter wheel, power box), the serial ports of the mount and the
   power box, the optics (focal length, aperture, reducer) and the site (latitude,
   longitude, elevation). A USB GPS can fill the site in later.
2. **Connect**. Every device should end up ready; a device that fails says why, and
   the others carry on.

The phone gives its time to the box and the mount every time it connects, so the
clock is right in the field even without network or RTC battery.

## 5. The night

**Tonight** leads through the night: polar alignment, focus, framing the target and
the sequence. **Live** takes single frames and loops. **Session** shows what the box
is doing. The box runs the night by itself: you can lock the phone, or close the
browser, and come back to it later.

Frames go to `NOCS/<night>/<type>/<target>/<filter>/` on the USB drive (or the card),
and you can download them from the app.

## 6. At the end

- **Eject** the USB drive on Rig, under Storage, before unplugging it.
- **Shut down** on Rig, under This computer, and wait half a minute before you cut
  the power. Cutting it while the box writes can damage the card or the drive.

When something does not work, see [troubleshooting](troubleshooting.md).
