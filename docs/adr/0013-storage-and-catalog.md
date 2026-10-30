# 0013. Storage destinations, file layout and frame catalog

Date: 2026-10-30 · Status: Accepted

## Context

Phase 2 must keep every saved frame where the user chose, in folders a stacking
program can use as they are, with complete FITS headers, and let the phone list
and download them. Until now frames land in `<data dir>/frames/<date>/`. Facts
that shape the decision:

- The microSD that holds the OS is a **supported, common destination**: other
  appliances image to it routinely, and v0.1 treats it as the normal case. It is
  slower and wears out sooner than a USB SSD, which NOCS recommends without
  requiring. What must never happen is the OS disk filling up.
- Mounting is not nocsd's job: nocs-system will mount and eject drives through
  udisks2 in phase 6 (ADR 0010). In phase 2 an external drive is already mounted
  (fstab), and nocsd runs unprivileged.
- A mount point is just a directory: when the drive is missing, `/mnt/usb` is
  still there and writes to it silently go to the microSD underneath.
- Drives move between mount points (`/media/<user>/<label>` from udisks, a
  different fstab line, a PC). Their filesystem UUID stays, and any user can
  read it from `/dev/disk/by-uuid/`, `/proc/self/mountinfo` and `/sys/dev/block/`.
- USB sticks are often FAT/exFAT: case-insensitive, no `:*?"<>|` in names.
- A frame reaches nocsd as a FITS file it can move (ADR 0012), with most headers
  written by the driver: RA/DEC, FILTER, FOCUSPOS, GAIN, OFFSET, CCD-TEMP,
  SITELAT/SITELONG (snooped from the mount), FOCALLEN/APTDIA (from
  `SCOPE_INFO`), DATE-OBS. Missing are OBJECT, SITEELEV, the site name, the
  cooler set point and the software that wrote the file. On ext4, renaming over
  an existing file flushes it first (~2 s for 26 MP on the microSD).
- The system clock is not set by NOCS in phase 2, so it is only as right as the
  OS keeps it, and the Pi's time zone is usually UTC: the "local date" is
  unreliable even when the UTC time is right.

## Decision

### Destinations

- **Candidates** are the configurable internal directory (`NOCS_STORAGE_DIR`,
  default the data directory, shown as "Internal") and the mounted filesystems
  under `/media/` and `/mnt/` (up to two levels, so udisks'
  `/media/<user>/<label>` counts) backed by a block device. Each is reported with
  label, filesystem, total and free space, whether nocsd can write to it,
  whether it is on the same disk as `/` (`system`) and whether that disk is an SD
  card (`sd`). The UI may recommend an external SSD; it never blocks the choice.
- **Automatic by default:** frames go to an external drive (a writable candidate
  not on the system disk; with several, the one with most free space) when one
  is mounted, and to Internal otherwise, so saving works out of the box. Once a
  night has saved frames to an external drive in automatic mode, that drive is
  that night's destination: if it disappears, saving fails as below instead of
  continuing on the microSD, and the UI offers to switch.
- The user may instead choose a destination explicitly, Internal included; the
  choice is kept until changed and never switched automatically.
- A volume is identified by its **filesystem UUID**; one without (tmpfs, some
  network or container mounts) by `mount:<mount point>`, which only works while
  it stays mounted there.
- The destination choice (automatic, or volume id + directory within it), the current
  **target name** and the **file name template** are kept in
  `<config dir>/storage.json`, survive restarts, and are published under
  `storage` in the state with the candidate list. nocsd re-reads the mount table
  and free space every 5 s.
- **Before every save** nocsd checks that the destination directory is on the
  selected volume (same device as the mounted filesystem with that UUID), is
  writable, and keeps at least 1 GiB free after the frame, so the system disk
  never fills up. If not, the exposure job fails with an explanation and the
  frame is kept in `<data dir>/unsaved/` (same reserve) so it is not lost. There
  is never a silent switch to another disk.

### Layout and names

- Frames go below `<destination>/NOCS/<night>/`, by type:
  - lights: `Light/<target>/<filter>/`
  - flats: `Flat/<filter>/`
  - darks and biases: `Dark/`, `Bias/`

  where:
  - `<night>`: the date at the start of the night, `YYYY-MM-DD`. It is the date
    of the UTC exposure start (system clock) plus the site longitude / 15 h
    (local mean solar time, pure arithmetic: no time zone database, no network)
    minus 12 h, so it changes at local noon. Without a site in the profile, the
    system time zone is used instead of the longitude.
  - `<target>`: the current target name, or `Untitled`. Names are matched
    case-insensitively against known targets (FAT) and sanitised: Unicode
    letters and digits, `-_.+`, spaces become `_`, at most 64 characters.
  - `<filter>`: the FILTER header (or the filter wheel role's current filter);
    the level is omitted when there is no filter.
- Only the **main camera** saves frames. Guide camera exposures are previews for
  framing and focusing the guide scope; PHD2 keeps its own dark library.
- **File name template** (configurable, validated when set): fields `{target}
  {night} {type} {filter} {exposure} {gain} {offset} {temperature} {binning}
  {camera} {datetime} {seq}`, only plain names (no attribute or index access).
  Default `{datetime}_{type}_{filter}_{exposure}s_{temperature}C_{seq}` →
  `20261031-031502_Light_Ha_300s_-10C_0007.fits`. `datetime` is the UTC exposure
  start; `seq` counts frames in the directory (4 digits). Empty fields drop out
  and repeated separators collapse.
- A name is never reused: if the file exists, `_2`, `_3`… is appended. The frame
  is moved with `shutil.move` to that new name, never over an existing file: a
  rename when the destination is on the same filesystem as the incoming frame
  (the microSD case, free), a copy otherwise.

### FITS headers

- In a thread (never on the event loop, never in the imaging worker so previews
  are not delayed), before the move: read the header and **add what the driver
  did not write**: `SITENAME`, `SITELAT`/`SITELONG`/`SITEELEV` (profile site),
  `FOCALLEN`/`APTDIA`/`FOCRATIO` (profile optics, focal length with the reducer),
  `SET-TEMP` (cooler target). The keys NOCS owns are always set: `OBJECT` (the
  target, for lights) and `SWCREATE = 'NOCS <version>'`, the keyword other
  capture programs use for the creating software and its version.
- The new header is written in place when it fits in the existing header blocks
  (the usual case: INDI leaves padding); otherwise the frame is written once to
  its destination with the larger header, instead of being moved. Pixel data is
  never decoded or rescaled.

### Catalog

- SQLite (stdlib `sqlite3`) at `<data dir>/catalog.sqlite`, WAL mode,
  `synchronous=NORMAL`, one connection used from worker threads behind a lock.
  Tables:
  - `volumes`: id, fs UUID or `mount:` id, label, last mount point, last seen.
  - `targets`: id, name (unique, case-insensitive); coordinates come in phase 3.
  - `nights`: id, night date, site, first and last frame time. A night groups
    what was saved from noon to noon, matching the `<night>` folder; it needs no
    start or stop, and is created by its first saved frame.
  - `frames`: id, night, target, volume, path relative to the volume's root
    (unique per volume), size, exposure start (UTC), exposure, type, filter,
    profile, camera device, gain, offset, binning, sensor temperature, width,
    height, and metrics: star count and HFR (null until the worker measures them).
- A frame row is written right after the move; its metrics are filled in when
  the worker's analysis comes back (analysis failures leave them null). Frames
  from loop mode and unsaved exposures are not catalogued.
- **Removed drive:** rows stay. A frame is `available` when its volume is
  mounted now, under whatever mount point; downloads of an unavailable frame
  answer 409 naming the volume. Files deleted outside NOCS answer 404; a rescan
  that reconciles the catalog with the disk is left for later.
- **Schema migrations:** `PRAGMA user_version` holds the schema version; the code
  carries an ordered list of migration scripts, applied at startup each in its
  own transaction (SQLite DDL is transactional), after copying the database to
  `catalog.sqlite.v<old>.bak` with the backup API. A database newer than the code
  is not touched: the catalog is disabled and saving fails with that reason.
  There are no downgrades.

### API

- `PUT /api/storage/destination`, `PUT /api/storage/target`,
  `PUT /api/storage/template`; everything else about storage is in the state.
- `GET /api/nights`: nights, newest first, with frame counts and size per type,
  target and filter.
- `GET /api/frames?night=&target=&type=&filter=&before=&limit=`: newest first,
  paged by id.
- `GET /api/frames/{id}/file`: the FITS, as an attachment (range requests
  supported, so phones can resume).
- `GET /api/nights/{id}/zip?target=&type=&filter=`: a night's frames, or part of
  them, as one zip streamed while it is built, with paths as below `NOCS/`.
  `ZIP_STORED` (FITS barely compress and the Pi's CPU is better spent
  elsewhere), zip64 over 4 GB. Built with `zipstream-ng` (LGPL-3.0, pure Python),
  which computes the size in advance, so the response has a `Content-Length` and
  the phone shows progress. There is no size limit. Answers 409 before starting
  if any volume of those frames is missing.
- The camera state's `last_frame` gains the catalog id and the path relative to
  the destination.

## Consequences

- Imaging to the microSD works with no setup and costs nothing extra (frames are
  renamed, not copied); an external drive is one choice away.
- Frames are found again after a drive moves to another mount point or comes
  back after being removed; the catalog stays on the server, so a drive taken to
  a PC carries only its folders and headers.
- A missing drive fails the exposure instead of filling the microSD by accident;
  a sequencer (phase 6) will decide whether to pause.
- Unplugging a drive while it is being written can still lose the last frames
  and corrupt the filesystem: ejecting comes with nocs-system (phase 6); until
  then the user stops capturing first.
- A zip download that breaks starts again from zero, and a whole night over the
  Pi's access point can take an hour: how it behaves in the field decides whether
  it needs resuming or an SMB share (design §8, later) sooner. Single frames
  resume.
- Moving frames to a USB drive is a copy, ~0.2–0.5 s for 26 MP before the
  preview starts.
- Night folders depend on the system clock's UTC time being right; setting the
  clock from the client is a separate decision.
- Frames saved before this change under `<data dir>/frames/` are not imported.
- Authentication (stage 2.5) will protect the download endpoints like the rest.
