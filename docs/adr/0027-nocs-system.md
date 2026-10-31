# 0027. nocs-system: what the privileged helper does, and what nocsd does itself

Date: 2026-10-31 · Status: Proposed

## Context

ADR 0010 put the operating system's operations in a separate privileged service,
`nocs-system`, used only by nocsd over a Unix socket, so that a bug or a
compromise in the network-facing daemon cannot reconfigure the system directly.
Phase 6 builds it, and has to decide where the line runs. Facts:

- Much of what the design gives nocs-system (§4.2) needs **no privileges to
  read**: nocsd already finds mounted drives and their free space from
  `/proc/self/mountinfo` and `/sys` (ADR 0013). Temperatures, under-voltage,
  throttling and memory are in `/sys` and `/proc`; NetworkManager, systemd and
  chrony answer status queries from any user; the journal is readable by the
  group `systemd-journal`.
- What **needs privileges**: changing network connections and the access point,
  mounting and ejecting drives, setting the clock and the host name, rebooting
  and powering off, restarting indiserver and PHD2, installing updates, resetting
  a USB device, changing the firewall and SSH.
- polkit could let the `nocs` user make the D-Bus calls itself (NetworkManager,
  udisks2, timedated, logind, systemd). Each of those interfaces is broad: any
  connection, any device with any mount options, any unit. apt has no such
  interface at all.
- Every service involved ships a command-line client (`nmcli`, `udisksctl`,
  `chronyc`, `hostnamectl`, `systemctl`, `apt-get`) that is itself a D-Bus or
  socket client, and that the maintainer can run by hand to check what NOCS does.
- nocs-system runs as root. Importing nocsd's dependencies (NumPy, OpenCV, the
  web stack) into it would put them all in a privileged process.

## Decision

- **nocsd reads, nocs-system writes.** Everything that can be read without
  privileges is read by nocsd and published in its state (`system`). nocs-system
  only performs **a closed list of operations**, each with validated arguments,
  and holds no state of its own beyond what the OS keeps.
- **Transport:** a Unix socket, `/run/nocs-system/socket`, owned by root with
  group `nocs`, mode 0660. nocs-system checks the peer's credentials
  (`SO_PEERCRED`) and accepts only the `nocs` user. One JSON request per line,
  `{"id", "op", "args"}`; replies `{"id", "result"}` or `{"id", "error"}`; long
  operations (updates) send progress lines first. No HTTP.
- **Operations** for v0.1, by group: `power` (reboot, power off), `hostname`,
  `network` (join, forget, access point settings, mode), `storage` (mount,
  eject), `time` (set from the client), `services` (restart `nocs-indiserver` or
  `nocs-phd2`), `update` (check, install, roll back), `ssh` (on, off, keys),
  `usb` (reset a device by its path under `/dev/bus/usb`). Each group is switched
  on in `/etc/nocs/system.conf`: `nocs` alone enables `services`;
  `nocs-appliance` enables all of them. A PC therefore cannot be rebooted or
  re-networked from the web app unless its owner says so.
- nocs-system calls the **command-line tools** with argument lists, never a shell,
  so a value cannot become a command.
- **Code:** the package `nocs.system` with its own entry point `nocs-system`, in
  the same project, lockfile and `.deb` as nocsd (ADR 0025), using only the
  standard library and anyio. A test checks that it imports nothing else from
  `nocs`. The unit runs as root under systemd's sandboxing options that leave the
  tools working (`NoNewPrivileges`, `PrivateTmp`, `ProtectHome`, restricted
  address families). Those options give it a mount namespace of its own, so
  nocs-system never mounts a drive itself: `systemd-mount` asks systemd to, in the
  system's namespace, after a file system check, at `/media/nocs/<UUID>`, owned by
  `nocs` on filesystems without owners (FAT, exFAT, NTFS); on the others nocs-system
  makes a `NOCS` folder for it. `systemd-umount` and `udisksctl power-off` eject
  it. udisks2, which ADR 0013 expected to mount drives, mounts them for the user
  who asks, which here would be root.
- nocsd's client reports an operation that nocs-system does not offer (no socket,
  or the group switched off) as unavailable in the state, and the app hides it.
- This refines ADR 0010 and replaces the top-level `system/` directory of the
  design's repository layout with `server/src/nocs/system/`.

## Consequences

- A compromised nocsd can still do what the list allows (reboot, change the Wi-Fi,
  eject a drive), but not run commands as root, mount arbitrary devices, or add a
  network connection with scripts.
- Reading needs no round trip through the helper, and works the same on a PC
  without nocs-system.
- Operations are testable on any machine with fake tools on the `PATH`; whether
  the real tools behave as expected is checked on a test Pi.
- Adding an operation means changing nocs-system, its tests and its list, which a
  reviewer sees in one place.
