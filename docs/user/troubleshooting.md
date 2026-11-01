# Troubleshooting

When a problem is not listed here, download the **diagnostics** (Rig → This
computer → Download diagnostics) and attach the zip to a report. It holds the
versions, the state and the last day of logs. It includes your site and your
equipment, so check it before posting it publicly.

## Reaching the box

**`nocs.local` does not open.**
- On the box's own Wi-Fi (`NOCS-xxxx`), open <http://10.42.0.1> instead.
- On another network, some phones do not resolve `.local` names. Find the box's
  address in your router, or plug in a network cable and try again.
- With two boxes on one network, the second one may answer as `nocs-2.local`. Give
  each its own name (Rig → This computer → Rename).

**The phone keeps leaving the box's Wi-Fi.** The phone prefers networks with
internet. Turn off "switch to mobile data" (Android) or "Wi-Fi assist" (iOS), or
answer "stay connected" when the phone asks.

**I renamed the box and the app asks me to pair again.** A phone is paired with the
name it used: after a rename, open `http://<new name>.local` and pair it with your
passphrase.

**I forgot the box's Wi-Fi password.** Reach the box another way (your home Wi-Fi, if
it knows it, or a network cable) and set a new one on Rig → Network → Access point.
Otherwise, write the image again.

**I forgot the owner passphrase.** Paired phones keep working: nothing needs it until
you pair another device. To reset it you need a shell on the box (an SSH key given
through Raspberry Pi Imager):

```sh
sudo rm /var/lib/nocs/config/auth.json && sudo systemctl restart nocsd
```

The next visit sets a new passphrase; every device has to pair again.

## Warnings in the app

**"The power supply is too weak".** The Pi gets less than 5 V. It may slow down,
lose USB devices or damage its card. Use the official 27 W supply, or a 5 V / 5 A
one; a long or thin cable has the same effect. NOCS also says when it happened last.

**"The CPU runs slower than it can" / "The CPU is hot".** Give the Pi an active
cooler, and shade it during the day.

**"System disk almost full".** Save frames to a USB drive, or download and delete old
nights.

**The clock is wrong, or "Frame times are corrected".** In the field the box takes the
time from your phone when it connects (or from a USB GPS). Without an RTC battery,
the Pi's clock starts wherever it stopped. Open the app once at the start of the night.

## Devices

**A device does not connect.** Rig shows why next to it. Check the cable and its
power, and that the profile names the right driver and, for mounts and power boxes,
the right serial port (`/dev/serial/by-id/…`).

**INDI "Not answering".** NOCS restarts indiserver by itself after about a minute;
you can also restart it on Rig → This computer → Restart INDI. Every device
reconnects; an exposure in progress is lost.

**A device stops answering** (Error or Offline while the rig is connected). Rig
offers **Restart driver** under it, and **Power cycle** when the profile says which
power box output feeds it: the output goes off for 5 seconds, then the driver
restarts. A running sequence does both by itself before retrying (first the driver,
then the power), and lists them in its events. The mount is never power cycled: it
would lose its position.

**A USB drive is "Not mounted".** Rig shows why: NOCS reads FAT, exFAT, NTFS, ext4,
btrfs and XFS. An ejected drive stays unmounted until you unplug it.

## Updates

Updates need internet: join a network with internet (Rig → Network), then Rig → This
computer → Updates → Check. NOCS installs them only when you say so, never during a
session, and restarts itself at the end. If the new version misbehaves, **Go back**
installs the previous one.
