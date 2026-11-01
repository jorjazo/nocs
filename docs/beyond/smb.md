# SMB share plan — the box's images on a desktop PC

Status: in progress (S0 decided 2026-11-01, S1–S3 implemented) · Last updated: 2026-11-01 · Roadmap: [Beyond v0.1](../roadmap.md#beyond-v01-unordered-backlog) · Decision: [ADR 0037](../adr/0037-smb-share.md)

Goal: at home, a desktop PC (Windows, macOS, Linux) opens the box's frames as a
network folder, without downloading zips through the phone or taking the USB drive
out: the box shows up under Network in Explorer and in Finder's sidebar, opens
without a password, and a stacking program reads the night's folders in place or
copies them off.

**Exit (test Pi, then the lab Pi):** with the share on, a Windows 11 PC and a Mac on
the home network find the box by themselves, open last night's folder on the microSD
and on a USB SSD as a guest, copy it at the network's speed, and cannot change
anything in it nor see anything but frames; with the share off, port 445 is closed
and nothing announces it.

## What exists

- Frames live below `<destination>/NOCS/<night>/` (ADR 0013): the internal
  destination `/var/lib/nocs` on the appliance, next to the catalog and `config/`
  (`auth.json`), and USB drives that nocs-system mounts at `/media/nocs/<UUID>`
  (6.5). Downloads from the app are one frame or one night's zip, over HTTP.
- nocs-system performs a closed list of operations, switched on by group in
  `/etc/nocs/system.conf.d/` (ADR 0027); the appliance enables every group.
- `nocs-appliance` owns the network: NetworkManager on `wlan0` (access point
  `10.42.0.1/24` or a home network, ADR 0028) and `eth0`, an nftables firewall that
  lets in 22, 80, mDNS, DHCP and DNS only, avahi announcing `_http._tcp`.
- Found while reading for this plan: nocs-system logs every request's arguments
  (`server.py`, `log.info("%s %s", op, json.dumps(args))`), so the Wi-Fi passwords of
  `network.join` and `network.access_point` reach the journal, and from there the
  diagnostics bundle (`services/diagnostics.py` includes nocs-system's journal).
  Fixed on its own, before this plan: [jorjazo/nocs#1](https://github.com/jorjazo/nocs/pull/1).

## Facts that shape it

- **Windows 11** refuses guest logons to SMB shares (`AllowInsecureGuestAuth` off
  since Windows 10 1709 Enterprise and Education, and in Pro and Home since 24H2),
  requires SMB signing by default since 24H2 (a guest session cannot sign, so this
  refuses guests too), and has no SMB1 or NetBIOS browsing. Both are client
  settings the PC's administrator can change (`Set-SmbClientConfiguration
  -EnableInsecureGuestLogons $true -RequireSecuritySignature $false`, or the same in
  Group Policy); Windows 10 Home and Pro accept guests as they come: the Network
  folder finds machines by **WS-Discovery** (UDP 3702, then HTTP on TCP 5357).
  Windows 10 and 11 resolve `.local` names by mDNS.
- **macOS** finds SMB servers by mDNS (`_smb._tcp`; `_device-info._tcp` picks the
  icon) and speaks SMB3. Linux file managers browse mDNS too.
- **Samba** (`smbd`) is Ubuntu's SMB server. Built with avahi, it announces
  `_smb._tcp` itself while it runs (`multicast dns register`). WS-Discovery is a
  separate daemon, `wsdd` (Python, Ubuntu universe). `nmbd` (NetBIOS) is not needed.
  `smbd` can run on a configuration file of its own (`--configfile`), next to the
  `smbd.service` the package ships.
- Samba serves guests (`map to guest = Bad User`, `guest ok`) as a Unix account of
  its choosing (`guest account`): the `nocs` system user (no shell, no Unix
  password), so files are read with the same rights as nocsd. Without guests it would
  keep an NT hash (unsalted MD4) of a user's password in its own passdb.
- The catalog (ADR 0013) knows each frame; files changed or deleted outside NOCS turn
  into 404s, and a rescan is left for later. A desktop writing to the microSD could
  fill the system disk past the 1 GiB reserve NOCS keeps.
- The Pi 5 has ARMv8 AES, so SMB3 signing and encryption cost little; the limits are
  the network (gigabit Ethernet ~110 MB/s; 2.4 GHz Wi-Fi of the access point a few
  MB/s) and the microSD, which frame saving shares (soak tests: ~2 s to flush a 26 MP
  frame on the lab Pi's card).
- The appliance is the only place where NOCS runs the network and the firewall. On a
  PC, `nocs` alone leaves both to the owner, who has their own file sharing.

## Decisions (taken 2026-11-01)

1. **Samba itself.** *Decided:* a dependency of `nocs-appliance` (`samba`, `wsdd`,
   no recommends), so it is on every image and on a flashed Pi after an update, and
   works in the field without internet; **off by default**: the package's
   `smbd`/`nmbd`/`samba-ad-dc` units masked, NOCS's own units started only when the
   owner switches the share on. Cost: disk (Samba pulls Python modules; to measure,
   expected ~100 MB on the 7 GB root), no RAM or open port while off, and Samba's
   security updates downloaded like the rest (6.10).
   (Rejected: an optional `nocs-share` package installed from the app (needs
   internet at the moment the owner wants it, usually in the field; apt from the app
   again); in the image only, not a dependency (Pis flashed before never get it).)
2. **Access.** *Decided:* **read-only.** The share is for taking frames off the
   box; deleting or renaming them behind the catalog leaves it wrong, and writing to
   the microSD can fill the OS disk. Deleting a night belongs in the app, where the
   catalog follows (a later item).
3. **Authentication.** *Decided:* **anonymous (guest), no password:** the share
   holds only astronomical images and is read-only. Samba maps every client to the
   guest (`map to guest = Bad User`, `guest only = yes`), read as the `nocs` user;
   no passdb, nothing secret to set, store or keep out of the state. The cost, in
   the user documentation: **Windows 11 (24H2) refuses guests** until the PC's
   administrator allows them (the command above; Windows 10 Home and Pro need
   nothing), and anyone on the home network, or on the access point once they know
   its password, can read the frames while the share is on. **Besides the guest, a
   fixed, well-known login, `nocs` / `nocs`** (printed in the docs and on the
   screen), which Windows 11 accepts without changing its settings: it protects
   nothing either. nocs-system writes it into Samba's passdb (`smbpasswd -s` on its
   standard input, in `/var/lib/nocs-share/`) when the share is switched on; a wrong
   password for `nocs` is refused, any other user name is the guest.
4. **Folders.** *Decided:* **only the folders where frames are saved, one share per
   storage volume, each the volume's `NOCS` folder:** `Internal` → `/var/lib/nocs/NOCS`, and each USB drive mounted
   by nocs-system → `/media/nocs/<UUID>/NOCS`, named by its label (`USB-<4 hex of the
   UUID>` without one; deduplicated, at most 32 characters). Never the
   data directory (it holds `config/auth.json` and the catalog) nor a drive's other
   files. nocs-system builds the list itself from what is mounted under `/media/nocs`
   and from its configured internal directory, so nocsd never names a path for root to
   share. Mounting a drive adds its share and ejecting one removes it first (so smbd
   does not keep it busy); while the share is on, nocsd asks for a refresh every 10 s,
   which rewrites the configuration only when something changed (a drive pulled out). Samba's `follow symlinks = no`
   keeps a link inside a folder from reaching anything else. (Rejected: one `NOCS`
   share with a folder per volume, which needs symlinks across filesystems and
   Samba's `wide links`, or bind mounts.)
5. **Network exposure.** *Decided:* the share is reachable **only from the box's
   LAN interfaces** — `wlan0` (access point or home Wi-Fi) and `eth*` — enforced by
   the firewall by interface, not by address (home networks with global IPv6 make
   address lists wrong): TCP 445, WS-Discovery UDP 3702 and TCP 5357, and nothing else
   (no NetBIOS 137–139). The rules sit in `firewall.nft` permanently; while the share is
   off nothing listens there, as with SSH without keys. A future remote-access
   interface (VPN) does not get the share unless a later decision says so. Samba
   accepts SMB 2.1 and newer (`server min protocol = SMB2_10`) and no NTLMv1. Discovery: smbd's own mDNS
   registration (`_smb._tcp`, gone when it stops) plus a `_device-info._tcp` record for
   the Finder icon, and `wsdd` on the same interfaces for Windows; both only while the
   share is on.
6. **Control.** *Decided:* a **`share` group in nocs-system** (ADR 0027), on in
   `appliance.conf`: `share.status` (on, running, the shares, connected clients from
   `smbstatus --json`), `share.enable {on}`, `share.refresh`. The OS keeps the setting (the units enabled or not), so nocs-system
   still holds no state of its own. NOCS's units: `nocs-share.service` (smbd on
   `/etc/nocs/share/smb.conf`, which nocs-system writes) and `nocs-wsdd.service`.
   Switching it on or off is allowed during a job: it does not touch a session.
   nocsd publishes `share` in the state; `PUT /api/system/share`, owner only.
7. **Pi impact.** *Decided:* nothing runs while off. While on, smbd and wsdd run
   with `Nice=10`, `IOSchedulingClass=best-effort` priority 7 and a `MemoryMax`, so a
   copy yields to frame saving; Samba logs to the journal at level 1 (no
   `/var/log/samba` files), printing is off, and its locking and cache databases go to
   `/run`. Read-only and without a passdb, it writes next to nothing to the microSD
   (atime, which `relatime` writes at most once a day per file). S5
   measures it: memory idle and copying, frame-save times during a copy, and disk
   writes from `/proc/diskstats`. A copy during a session is allowed; the UI says it
   can slow saving on the microSD.
8. **Where it exists.** *Decided:* **appliance only.** On a PC `nocs` alone has no
   `share` group, and the app hides the section, as it does the network.
9. **First run.** *Decided:* not asked at the first run (it already asks for the
   access point, country and home Wi-Fi); offered on Rig.

## Stages

| # | Stage | Contents | Check | Estimate | Status |
|---|---|---|---|---|---|
| S0 | Decisions | This plan; ADR 0037 | Review with the maintainer | 2 h | Done: decided 2026-11-01 |
| S1 | nocs-system `share` | The `share` group: `smb.conf` built from the volumes (a pure function), `status`, `enable`, `refresh`; the `nocs` / `nocs` login; `systemctl`, `smbpasswd`, `smbcontrol`, `smbstatus` with argument lists | Unit tests with fake tools on the `PATH` (as `test_system.py`, `test_network.py`): the config for no drives, two drives, a label clash, an unlabelled drive; refusals | 3–4 h | Implemented: `nocs.system.share` (`share.status`, `share.enable`, `share.refresh`); mounting and ejecting a drive refresh the share, ejecting closes its share before unmounting; the group is switched on by the appliance in S2 |
| S2 | Packaging | `nocs-appliance`: `Depends` on `samba` and `wsdd`; masks Samba's own units in `postinst`; `nocs-share.service`, `nocs-wsdd.service` (priorities, sandboxing); firewall rules by interface; `share` in `appliance.conf`; image build unchanged but bigger | `packaging/deb/test.sh` with the appliance in the systemd container: switch on with `nocs-system call`, `smbclient -N` lists and reads `Internal` as a guest, and as `nocs` / `nocs`; refuses a write, a wrong password for `nocs`, and sees no `config/`; off: nothing on 445. The image builds and its smoke test passes; its size noted | 4–6 h | Implemented: the units, masks, firewall rules and `share` in `appliance.conf`; `hostname.set` restarts the share's services. The generated `smb.conf` checked with Samba 4.23.6 in an Ubuntu 26.04 container (below); `test.sh` and the image's smoke test check the rest in CI |
| S3 | nocsd | `share` state (schemas, TS types), refresh when drives change, the endpoint | API tests with a fake helper; the schema test of the live state | 2–3 h | Implemented: `share` state (`on`, `running`, `shares`, `clients`) read every 10 s with a refresh first while on; `PUT /api/system/share {on}`; types regenerated |
| S4 | Web UI | Rig: "File sharing" under Network: switch (saying anyone on the network can read the frames), the shares and how to open them (`\\<name>.local\Internal`, `smb://<name>.local`, the `nocs` / `nocs` login for Windows 11), connected computers; en/es; `docs/ux.md`; `docs/user/` (quick start; troubleshooting: Windows 11 and guests) | Browser against a fake helper, phone and wide, Night mode, both languages | 3–4 h | |
| S5 | Test Pi | Windows 11, macOS, Linux on the home network and on the access point; Ethernet; discovery; throughput; frame saving during a copy; memory and disk writes | Test Pi window | 2–3 h | |

Total **16–22 h**. S1 and S2 first (S2 needs S1's config), then S3 and S4, S5 last.
One PR per stage.

## Measured

Ubuntu 26.04 container (amd64), 2026-11-01:

- `samba` 2:4.23.6 and `wsdd` 2:0.8 from the archive; with `--no-install-recommends`
  they add 62 packages and **136 MB** to a minimal image, most of it Python 3.14, which
  the Pi's image already has. `smbd` links libavahi-client. `wsdd` ships no unit; it
  runs with `--interface wlan0 --interface eth0` even when one of them is missing.
- `smbd` on the generated configuration (`testparm`: no warnings): a guest lists
  `Internal` and a drive's share and reads frames, so does `nocs` / `nocs`; a wrong
  password for `nocs` gets `LOGON_FAILURE`, another user name is the guest; writing and
  deleting get `ACCESS_DENIED`; a symlink to the data directory's `config/` inside the
  share gets `STOPPED_ON_SYMLINK`. Nothing was written outside `/run` and
  `/var/lib/nocs-share` (passdb and secrets, 0600). `smbd` used 30 MB RSS idle.
- `smbstatus --json` lists each session with its `remote_machine` (the client's
  address).

## Notes

- Shared files kept small: `api/schemas.py`, generated types, `api/system.py`,
  `services/system.py`, the Rig screen, `firewall.nft`, `appliance.conf`.
- Not in this plan: write access or deleting from the app, a share on PCs, SMB over
  remote access, Time Machine or other backups to the box.
