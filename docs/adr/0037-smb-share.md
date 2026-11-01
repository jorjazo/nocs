# 0037. An SMB share of the frames for desktop computers

Date: 2026-11-01 · Status: Proposed (draft: access, authentication and folders decided
by the maintainer; the rest are the plan's recommendations)

## Context

Frames leave the box today one at a time or as a night's zip, downloaded through
the web app (ADR 0013), or on a USB drive carried to a PC. At home, a desktop PC
should open them as a network folder: stacking programs read them in place, file
managers copy them at the network's speed. The design leaves it for later (§8); the
plan is [beyond/smb.md](../beyond/smb.md). Facts that shape the decision:

- Windows 11 (24H2) refuses guest logons to SMB shares and requires signing, which a
  guest session cannot do, until the PC's administrator changes both; Windows 10 Home
  and Pro accept guests. Windows has no NetBIOS browsing any more, and finds machines for its Network folder by WS-Discovery (UDP
  3702, TCP 5357). macOS and Linux find SMB servers by mDNS (`_smb._tcp`). Windows
  10 and 11 resolve `.local` names.
- Samba's `smbd` is Ubuntu's SMB server; built with avahi it announces `_smb._tcp`
  while it runs; it can use a configuration file of its own. WS-Discovery needs the
  separate `wsdd`. Samba serves guests as a Unix account of its choosing.
- Frames sit below `<destination>/NOCS/` (ADR 0013): on the appliance the internal
  destination is `/var/lib/nocs`, next to the catalog and `config/auth.json`; USB
  drives are mounted by nocs-system at `/media/nocs/<UUID>` (ADR 0027).
- The catalog knows every frame; changes made outside NOCS make it wrong, and writing
  to the microSD from outside can fill the system disk past NOCS's reserve.
- The appliance's network and firewall belong to `nocs-appliance` (ADR 0028): `wlan0`
  (access point or home Wi-Fi) and Ethernet are its only interfaces today. The state is
  visible to observers, so it never holds secrets (ADR 0014).

## Decision

- **Samba on the appliance only, off by default.** `nocs-appliance` depends on
  `samba` and `wsdd`; Samba's own units are masked, and NOCS runs `smbd` as
  `nocs-share.service` on `/etc/nocs/share/smb.conf` and `wsdd` as
  `nocs-wsdd.service`, both started only while the owner has the share on. A PC with
  `nocs` alone has no share.
- **Read-only.** The share is for taking frames off the box. Deleting belongs in the
  app, where the catalog follows.
- **Anonymous:** every client is the guest (`map to guest = Bad User`, `guest only`),
  read as the `nocs` system user; no password, no passdb. The share holds only
  astronomical images, read-only. Anyone on the box's networks can read them while
  the share is on, and the user documentation says how to let Windows 11 in.
- **Only the folders where frames are saved, one share per volume, its `NOCS`
  folder:** `Internal` for the internal destination, and one per USB drive mounted
  by nocs-system, named by its label.
  nocs-system builds the list from what it mounted and from its configured internal
  directory, so nocsd never names a path to share; nocsd asks it to refresh when the
  drives change. Symbolic links are not followed.
- **LAN only:** the firewall accepts TCP 445, UDP 3702 and TCP 5357 on `wlan0` and
  `eth*` only; no NetBIOS. Samba accepts SMB 2.1 and newer. Discovery by smbd's mDNS
  registration (plus `_device-info._tcp`) and `wsdd`, only while on.
- **Control through nocs-system** (ADR 0027), a new group `share` enabled by the
  appliance: `share.status`, `share.enable`, `share.refresh`. The OS keeps whether it
  is on (the units enabled). Allowed while a job runs. nocsd
  publishes `share` in the state and offers `PUT /api/system/share` to the owner.
- **Low priority on the Pi:** both units run niced, at the lowest best-effort I/O
  priority, with a memory limit; Samba logs to the journal only, keeps its
  databases in `/run`, and has printing off.

## Consequences

- At home a PC finds the box and opens its nights without a password; in the field
  the same works on the access point, at Wi-Fi speed.
- A Windows 11 PC needs its guest and signing settings changed once, by its
  administrator, before it can open the share.
- Images stay safe from a desktop's mistakes, and the catalog stays right; freeing
  space still needs the app (or a USB drive taken to the PC).
- Turning the share on lets everyone on the home network (or on the access point)
  read the frames; nothing else on the box is reachable through it.
- The image grows by Samba and its Python modules; nothing runs or listens while the
  share is off.
- A copy over the share competes with frame saving on the microSD; lower priority
  reduces, not removes, the effect.
- Remote access, when it comes, does not expose the share unless a later ADR says so.
