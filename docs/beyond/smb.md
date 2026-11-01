# SMB share plan — the box's images on a desktop PC

Status: proposed (decisions open) · Last updated: 2026-11-01 · Roadmap: [Beyond v0.1](../roadmap.md#beyond-v01-unordered-backlog) · Decision: [ADR 0037](../adr/0037-smb-share.md)

Goal: at home, a desktop PC (Windows, macOS, Linux) opens the box's frames as a
network folder, without downloading zips through the phone or taking the USB drive
out: the box shows up under Network in Explorer and in Finder's sidebar, the owner
types one password once, and a stacking program reads the night's folders in place
or copies them off.

**Exit (test Pi, then the lab Pi):** with the share on, a Windows 11 PC and a Mac on
the home network find the box by themselves, open last night's folder on the microSD
and on a USB SSD with the password set from the phone, copy it at the network's
speed, and cannot change anything in it; with the share off, port 445 is closed and
nothing announces it.

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
  diagnostics bundle (`services/diagnostics.py` includes nocs-system's journal). An
  SMB password would take the same path. Stage S1 fixes it for all of them.

## Facts that shape it

- **Windows 11** refuses guest logons to SMB shares (`AllowInsecureGuestAuth` off
  since Windows 10 1709 Enterprise, and in every edition since 24H2), requires SMB
  signing by default since 24H2, and has no SMB1 or NetBIOS browsing: the Network
  folder finds machines by **WS-Discovery** (UDP 3702, then HTTP on TCP 5357).
  Windows 10 and 11 resolve `.local` names by mDNS.
- **macOS** finds SMB servers by mDNS (`_smb._tcp`; `_device-info._tcp` picks the
  icon) and speaks SMB3. Linux file managers browse mDNS too.
- **Samba** (`smbd`) is Ubuntu's SMB server. Built with avahi, it announces
  `_smb._tcp` itself while it runs (`multicast dns register`). WS-Discovery is a
  separate daemon, `wsdd` (Python, Ubuntu universe). `nmbd` (NetBIOS) is not needed.
  `smbd` can run on a configuration file of its own (`--configfile`), next to the
  `smbd.service` the package ships.
- Samba authenticates SMB2/3 users with NTLMv2 or Kerberos, and keeps an **NT hash**
  of each password in its passdb (`tdbsam`): unsalted MD4, as good as the password
  for logging in to the share and fast to brute-force if stolen. Each SMB user maps to
  a Unix account; the `nocs` system user (no shell, no Unix password) can be that
  account, so files are read with the same rights as nocsd.
- The catalog (ADR 0013) knows each frame; files changed or deleted outside NOCS turn
  into 404s, and a rescan is left for later. A desktop writing to the microSD could
  fill the system disk past the 1 GiB reserve NOCS keeps.
- The Pi 5 has ARMv8 AES, so SMB3 signing and encryption cost little; the limits are
  the network (gigabit Ethernet ~110 MB/s; 2.4 GHz Wi-Fi of the access point a few
  MB/s) and the microSD, which frame saving shares (soak tests: ~2 s to flush a 26 MP
  frame on the lab Pi's card).
- The appliance is the only place where NOCS runs the network and the firewall. On a
  PC, `nocs` alone leaves both to the owner, who has their own file sharing.

## Decisions (open; recommendation first)

1. **Samba itself.** *Recommended:* a dependency of `nocs-appliance` (`samba`, `wsdd`,
   no recommends), so it is on every image and on a flashed Pi after an update, and
   works in the field without internet; **off by default**: the package's
   `smbd`/`nmbd`/`samba-ad-dc` units masked, NOCS's own units started only when the
   owner switches the share on. Cost: disk (Samba pulls Python modules; to measure,
   expected ~100 MB on the 7 GB root), no RAM or open port while off, and Samba's
   security updates downloaded like the rest (6.10).
   *Alternatives:* an optional `nocs-share` package installed from the app (needs
   internet at the moment the owner wants it, usually in the field; apt from the app
   again); in the image only, not a dependency (Pis flashed before never get it).
2. **Access.** *Recommended:* **read-only.** The share is for taking frames off the
   box; deleting or renaming them behind the catalog leaves it wrong, and writing to
   the microSD can fill the OS disk. Deleting a night belongs in the app, where the
   catalog follows (a later item). *Alternative:* read-write, or read-write with
   deletes only (Samba cannot allow deleting without allowing writing).
3. **Authentication.** *Recommended:* **user `nocs` and a password the owner sets from
   the app**, separate from the owner passphrase (the NT hash is weak, and must not
   expose the passphrase); no guest share (Windows 11 refuses it, and a star party on
   a shared network would see everything). The password goes phone → nocsd (HTTP, as
   the passphrase and Wi-Fi passwords do, ADR 0014) → nocs-system (Unix socket) →
   `smbpasswd -s` on its **standard input**, never on a command line, into a passdb
   only root reads (`/var/lib/nocs-share/`, 0700). nocsd keeps no copy; the state
   says only `password_set` and the user name, never the password or its hash. nocs-system
   and nocsd never log it (S1). The share cannot be switched on before a password
   exists. Changing it does not cut a connected PC until it reconnects.
4. **Folders.** *Recommended:* **one share per storage volume, each the volume's
   `NOCS` folder only:** `Internal` → `/var/lib/nocs/NOCS`, and each USB drive mounted
   by nocs-system → `/media/nocs/<UUID>/NOCS`, named by its label (`USB-<4 hex of the
   UUID>` without one; deduplicated, at most 32 characters). Never the
   data directory (it holds `config/auth.json` and the catalog) nor a drive's other
   files. nocs-system builds the list itself from what is mounted under `/media/nocs`
   and from its configured internal directory, so nocsd never names a path for root to
   share; nocsd asks it to refresh when its own list of drives changes (it reads it
   every 5 s), and an ejected drive's share goes away. *Alternative:* one `NOCS` share
   with a folder per volume (needs symlinks across filesystems, Samba's `wide links`,
   which follows any link in the share) or bind mounts (more moving parts for a
   nicer tree).
5. **Network exposure.** *Recommended:* the share is reachable **only from the box's
   LAN interfaces** — `wlan0` (access point or home Wi-Fi) and `eth*` — enforced by
   the firewall by interface, not by address (home networks with global IPv6 make
   address lists wrong): TCP 445, WS-Discovery UDP 3702 and TCP 5357, and nothing else
   (no NetBIOS 137–139). The rules sit in `firewall.nft` permanently; while the share is
   off nothing listens there, as with SSH without keys. A future remote-access
   interface (VPN) does not get the share unless a later decision says so. Samba
   accepts SMB 2.1 and newer (`server min protocol = SMB2_10`), NTLMv2 only, signing
   as the client asks; encryption is the client's choice. Discovery: smbd's own mDNS
   registration (`_smb._tcp`, gone when it stops) plus a `_device-info._tcp` record for
   the Finder icon, and `wsdd` on the same interfaces for Windows; both only while the
   share is on.
6. **Control.** *Recommended:* a **`share` group in nocs-system** (ADR 0027), on in
   `appliance.conf`: `share.status` (on, running, password set, the shares, connected
   clients from `smbstatus --json`), `share.enable {on}`, `share.password {password}`,
   `share.refresh`. The OS keeps the setting (the units enabled or not), so nocs-system
   still holds no state of its own. NOCS's units: `nocs-share.service` (smbd on
   `/etc/nocs/share/smb.conf`, which nocs-system writes) and `nocs-wsdd.service`.
   Switching it on or off is allowed during a job: it does not touch a session.
   nocsd publishes `share` in the state; `PUT /api/system/share` and
   `PUT /api/system/share/password`, owner only.
7. **Pi impact.** *Recommended:* nothing runs while off. While on, smbd and wsdd run
   with `Nice=10`, `IOSchedulingClass=best-effort` priority 7 and a `MemoryMax`, so a
   copy yields to frame saving; Samba logs to the journal at level 1 (no
   `/var/log/samba` files), printing is off, and its locking and cache databases go to
   `/run`. Read-only, the only writes to the microSD are the passdb when the password
   changes (and atime, which `relatime` writes at most once a day per file). S5
   measures it: memory idle and copying, frame-save times during a copy, and disk
   writes from `/proc/diskstats`. A copy during a session is allowed; the UI says it
   can slow saving on the microSD.
8. **Where it exists.** *Recommended:* **appliance only.** On a PC `nocs` alone has no
   `share` group, and the app hides the section, as it does the network.
9. **First run.** *Recommended:* not asked at the first run (it already asks for the
   access point, country and home Wi-Fi); offered on Rig.

## Stages

| # | Stage | Contents | Check | Estimate | Status |
|---|---|---|---|---|---|
| S0 | Decisions | This plan; ADR 0037 | Review with the maintainer | 2 h | Proposed |
| S1 | nocs-system `share` | The `share` group: `smb.conf` built from the volumes (a pure function), `status`, `enable`, `password`, `refresh`; `smbpasswd`, `systemctl`, `smbcontrol`, `smbstatus` with argument lists, the password on stdin; secret arguments (`password`) never logged, Wi-Fi passwords included | Unit tests with fake tools on the `PATH` (as `test_system.py`, `test_network.py`): the config for no drives, two drives, a label clash, an unlabelled drive; refusals; nothing secret in the log | 4–5 h | |
| S2 | Packaging | `nocs-appliance`: `Depends` on `samba` and `wsdd`; masks Samba's own units in `postinst`; `nocs-share.service`, `nocs-wsdd.service` (priorities, sandboxing); firewall rules by interface; `share` in `appliance.conf`; image build unchanged but bigger | `packaging/deb/test.sh` with the appliance in the systemd container: switch on with `nocs-system call`, `smbclient` lists and reads `Internal` with the password, refuses a write and a wrong password; off: nothing on 445. The image builds and its smoke test passes; its size noted | 4–6 h | |
| S3 | nocsd | `share` state (schemas, TS types), refresh when drives change, the two endpoints, the state never holding the password | API tests with a fake helper; the schema test of the live state; a test that the password is in no response, state or log | 3–4 h | |
| S4 | Web UI | Rig: "File sharing" under Network: switch, password sheet (set, change; "not your NOCS passphrase"), the shares and how to open them (`\\<name>.local\Internal`, `smb://<name>.local`), connected computers; en/es; `docs/ux.md`; `docs/user/` (quick start, troubleshooting: Windows credentials) | Browser against a fake helper, phone and wide, Night mode, both languages | 3–4 h | |
| S5 | Test Pi | Windows 11, macOS, Linux on the home network and on the access point; Ethernet; discovery; throughput; frame saving during a copy; memory and disk writes | Test Pi window | 2–3 h | |

Total **18–24 h**. S1 and S2 first (S2 needs S1's config), then S3 and S4, S5 last.
One PR per stage.

## Notes

- Shared files kept small: `api/schemas.py`, generated types, `api/system.py`,
  `services/system.py`, the Rig screen, `firewall.nft`, `appliance.conf`.
- Not in this plan: write access or deleting from the app, a share on PCs, SMB over
  remote access, Time Machine or other backups to the box.
