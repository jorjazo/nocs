# 0043. An SSH login on the appliance whose password is the owner passphrase

Date: 2026-11-12 · Status: Proposed · Supersedes: [ADR 0026](0026-raspberry-pi-image.md) ("no login user and no password"), [ADR 0028](0028-networking.md) ("SSH takes keys only … password logins are never enabled") · Amends: [ADR 0025](0025-packaging-and-updates.md) (the service user's name), [ADR 0027](0027-nocs-system.md) (the user served, a new group of operations), [ADR 0039](0039-smb-share.md) (the Samba login's system user)

## Context

The image has no login user and SSH takes keys only (ADR 0026, ADR 0028): a shell on
the box needs a key given through Raspberry Pi Imager before the first boot. In
practice the owner needs a shell now and then (logs, a forgotten passphrase, a driver
to look at), usually after flashing without a key, and then has to flash again.
Facts that shape the decision:

- The box already has a secret the owner chose and remembers: the owner passphrase,
  set on the first visit and changeable through `PUT /api/auth/passphrase` (ADR 0014).
  nocsd sees it in clear only in those two requests; it keeps a scrypt hash.
- The services run as the system user `nocs` (ADR 0025), the user nocs-system serves
  (ADR 0027), with `/var/lib/nocs` as its home. A login user called `nocs` is the
  natural name for `ssh nocs@nocs.local`, so the two cannot share it.
- The `nocs` package also installs on someone's PC (ADR 0025), where a login user
  created by NOCS, let alone one with sudo, would be unwelcome; `nocs-appliance` is
  for dedicated boxes only.
- Setting a password is root's work: nocs-system's (ADR 0027), with the password on a
  tool's standard input, never on a command line that any user can read in `/proc`.
- cloud-init's `ssh_pwauth: false` in the image's user-data writes a global
  `PasswordAuthentication no`; an sshd `Match User` block overrides global settings for
  that user whatever their order, and a `Match` in a file of `sshd_config.d` ends with
  that file (checked with `sshd -T -C` on OpenSSH 10.6).
- Ubuntu's sshd already runs on the image, and the firewall already lets port 22 in
  (ADR 0028); with no password and no key, nobody could log in.

## Decision

- **The service user is renamed `nocsd`** (sysusers.d, the units of nocsd, indiserver
  and PHD2, tmpfiles, nocs-system's `[helper] user`, the share's owner, the packaging
  tests). `/var/lib/nocs` keeps its path. No migration: boxes are flashed again
  (nothing is compatible before v1.0).
- **`nocs-appliance` creates the login user `nocs`** in its `postinst`, once (if
  there is no `nocs` yet): `/home/nocs`, `/bin/bash`, groups `sudo` (sudo asks for
  the password, Ubuntu's default), `adm` (logs without sudo) and `nocsd` (reads the
  frames in `/var/lib/nocs`; `config/` stays nocsd's alone), **password locked**.
  The plain `nocs` package never creates it.
- **Its password is the owner passphrase.** nocs-system gets a group `account`,
  enabled only by `nocs-appliance`, with two operations. `account.password
  {password}` runs `chpasswd` with `nocs:<password>` on its standard input. It
  refuses a user that is missing, root, a system user (uid below 1000) or the user it
  serves, and a password with a line break or NUL. `password` is a secret argument,
  so its log line shows `***`, and a failing chpasswd's message has it masked.
  `account.status` says whether that user has a password: `set` when its field in
  `/etc/shadow` holds a hash, `locked` when it is locked (`!`), `*` or empty. Only
  that word leaves nocs-system, never the field.
- **nocsd calls it** after the passphrase is set up (`POST /api/auth/setup`) and after
  it changes (`PUT /api/auth/passphrase`), with the passphrase as the store keeps it
  (NFC). Where nocs-system does not offer the operation (a PC, or no nocs-system) it
  does nothing. A failure is logged as a warning and does not fail the request: the
  passphrase is the app's either way. The passphrase never reaches the state.
- **The state says where the login stands**, as `system.login`: `null` where there is
  no login NOCS manages (a PC, or nocs-system without the `account` group), else
  `{user, password}` with `password` one of `set`, `locked` or `failed`. nocsd reads
  `account.status` whenever nocs-system answers its periodic hello (so at start, and
  when nocs-system comes up late) and after each attempt to set the password;
  `failed` stands from a failed attempt in this run (chpasswd failed, or nocs-system
  was down while the login was known) until one succeeds. Why it failed stays in the
  log: the state is for observers too.
- **The web app** changes the passphrase in Rig → Access (owner only: the current
  one, the new one twice, at least 8 characters as the server counts them), and says
  there, on the appliance, that it is also the password of the SSH user and of sudo.
  Rig → This computer shows `ssh nocs@<name>.local` and, while the password is
  `locked` or `failed`, a warning whose button opens that form. **Entering the
  current passphrase as the new one** is how the owner gives the login the
  passphrase without changing it (a box that got `nocs-appliance` after its
  passphrase was set up, or a failed attempt): `PUT /api/auth/passphrase` accepts an
  identical new passphrase, verifies the current one as always, and sets the login's
  password again.
- **sshd** (`50-nocs.conf`): keys for everyone, `PermitRootLogin no`, passwords for
  `nocs` alone (`Match User nocs`). `nocs-appliance` makes sure SSH is enabled on a
  fresh install, and reloads sshd when it is configured. SSH stays on: a locked
  account lets nobody in until the passphrase is set, so nocs-system does not switch
  SSH on and off with it.
- **The image's user-data** keeps `users: []` (no default `ubuntu` user) and
  `ssh_pwauth: false`: cloud-init never removes a user, and the `Match` block
  overrides it for `nocs`. Raspberry Pi Imager's own user-data still creates its user;
  one called `nocs` only adds to the existing login, whose password the passphrase
  then replaces.
- **The SMB share's published login `nocs` / `nocs`** (ADR 0039) is now the login
  user in Samba's passdb (Samba wants a system user of that name), while guests and
  the login read the frames as `nocsd` (`force user`). Its Samba password is Samba's
  own: `unix password sync = no` is written out, so that it can never become the
  login's system password.

## Consequences

- `ssh nocs@nocs.local` with the owner passphrase works on a box flashed without any
  customisation, as soon as the passphrase is set, and `sudo` asks for the same
  passphrase.
- The passphrase now guards a root shell, not only the app. It was chosen for the app
  (8 characters at least) and travels over plain HTTP on the access point (ADR 0014,
  ADR 0028), protected by the Wi-Fi's WPA2 password. sshd is exposed on every network
  the box joins; a weak passphrase is now a weak root password there.
- A forgotten passphrase also loses the login: resetting it (troubleshooting) needs
  another way in, a key from Imager or flashing again.
- If nocs-system cannot set the password (it is down, chpasswd fails), the login keeps
  its old password, or stays locked, until the passphrase is set again; the app warns
  the owner (Rig → This computer), and nocsd's log says why. A `failed` from a run of
  nocsd does not outlive it: after a restart the state shows what `/etc/shadow` says
  (`set` may then be an old password).
- On a box upgraded rather than flashed, the old system user `nocs` would stand in
  the way of the login user; such boxes are flashed again instead.
- Removing `nocs-appliance` leaves the user `nocs` and its password, which then stops
  following the passphrase.
