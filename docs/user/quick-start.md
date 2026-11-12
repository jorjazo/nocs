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
   Imager also asks for a user: do not call it `nocs`, the box's own login (step 3).
4. Write. To boot from a USB SSD, write the SSD and take the microSD card out of the
   Pi.

## 2. First boot

Power the Pi on with **its USB devices unplugged**: cameras, USB drives and hubs,
USB 3 ones above all. USB 3 ports and cables drown out 2.4 GHz Wi-Fi, the only band
of the box's own network, and with them plugged in a phone a metre away may see the
network yet never manage to join it. Plug them in once the setup is done (and see
[troubleshooting](troubleshooting.md#reaching-the-box) for the field).

The first boot takes one or two minutes. Without a known network, the Pi then starts
its own Wi-Fi:

| Network | `NOCS-xxxx` (the last four characters of the Pi's serial number) |
|---|---|
| Password | `nocsnocs` (you change it in a moment) |
| Address | <http://nocs.local>, or <http://10.42.0.1> |

Join it from your phone. The phone will warn that this network has no internet:
stay on it. Then open <http://nocs.local> in the browser.

If you gave Imager your home Wi-Fi, join that network instead and open
<http://nocs.local> there.

## 3. Set up

1. **Owner passphrase.** Name this phone and choose a passphrase of at least 8
   characters. It pairs this phone, which then stays signed in. You need the
   passphrase again only to pair another phone or computer. It is also the password
   of the box's login, `nocs`, for a terminal: `ssh nocs@nocs.local`, and `sudo`
   asks for it too. If the passphrase changes, so does that password; until you set
   it, nothing can log in. Change it on Rig → Access → Owner passphrase; Rig → This
   computer shows the `ssh` command, and warns when that password is not the
   passphrase.
2. **Set up this box**, in steps; **Back** returns to an earlier one, and nothing
   changes until the last.
   1. **Access point**: your country, and a password of your own for the box's
      Wi-Fi (you may keep `nocsnocs`).
   2. **Home Wi-Fi** (optional): a network the box joins whenever it is in range,
      your home's for example.
   3. **Name**: the box's name, `nocs` until you change it. Phones and computers
      reach it as `http://<name>.local`; give each box a name of its own if you
      have more than one.
   4. **Site** (optional): where the rig stands, by name, latitude, longitude and
      elevation. A rough position is enough: a few kilometres off changes nothing,
      so the nearest town's coordinates from a map will do. Tonight's sky, go to
      and polar alignment need it; you may also leave it for later, in Rig.
   5. **Check and apply**: what the box will do. When you apply, it saves the site
      and makes it the active one, restarts its Wi-Fi with the new password (or
      leaves it for your home network), and the phone drops off it: follow it as
      the screen says, and open `http://<name>.local` again. After a new name the
      box asks for your passphrase once more.
3. Now plug the USB devices in.

## 4. Your equipment

On **Rig**:

1. **New profile**: pick the driver of each device (main camera, guide camera,
   mount, focuser, filter wheel, power box): type its model or maker in the driver
   field, e.g. `AM5`, and tap it in the list under the field. Then the serial ports
   of the mount and the power box, and the optics (focal length, aperture, reducer).
2. **Site**, unless you set it up in the first run: add the place where the rig
   stands (latitude, longitude, elevation) and make it the active one. It belongs
   to the box, not to the profile, and the mount gets it when it connects.
   Tonight's sky and polar alignment need it, but only roughly: a few kilometres
   off changes nothing. **From the mount** fills it in from the site the connected
   mount already has (one set with its hand controller or its own app, say), and
   **From the GPS** from a USB GPS's fix; you can still edit the values before
   saving.
3. **Connect**. Every device should end up ready; a device that fails says why, and
   the others carry on.

The phone gives its time to the box and the mount every time it connects, so the
clock is right in the field even without network or RTC battery.

## 5. The night

**Tonight** leads through the night with its checklist: connect, polar alignment,
focus, framing the target and guiding. The next step, with the big button, is the
first one not done that can run; a step that cannot run yet says what is missing (the
site, the plate solver, a device that is not ready, a parked mount) and links to
where to fix it, and the checklist moves on to the next step that can. **Live** takes
single frames and loops. **Session** shows what the box is doing. The box runs the
night by itself: you can lock the phone, or close the browser, and come back to it
later.

Frames go to `NOCS/<night>/<type>/<target>/<filter>/` on the USB drive (or the card),
and you can download them from the app. At home, a computer can also open them as a
network folder: switch on **File sharing** on Rig, then open `\\nocs.local\Internal`
in Windows' File Explorer or `smb://nocs.local` on a Mac (Finder → Go → Connect to
Server) or on Linux. It is read-only and needs no password, so anyone on that network
can read the frames while it is on; Windows 11 asks for a login: user `nocs`, password
`nocs`.

## 6. At the end

- **Eject** the USB drive on Rig, under Storage, before unplugging it.
- **Shut down** on Rig, under This computer, and wait half a minute before you cut
  the power. Cutting it while the box writes can damage the card or the drive.

When something does not work, see [troubleshooting](troubleshooting.md).
