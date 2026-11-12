# Field notes: `v0.1.0rc4` on the rig, 2026-11-11

Working notes while the maintainer tests the rig outdoors from the `rc4` card.
Findings move to [phase 6's findings](phase-6.md#612-findings-from-v010rc1) (or the
phase they belong to) once decided.

| Time | Where | Finding | Status |
|---|---|---|---|
| night | The box's access point, outdoors | Neither a laptop nor a phone could join `NOCS-xxxx` from about a metre away: the laptop saw the network now and then, the phone always, and neither completed joining (the same as on rc2's night). **The two USB 3 devices on the Pi were the cause:** with them unplugged both joined every time, whatever the cables tried. USB 3 ports and cables are known to radiate in the 2.4 GHz band, and the access point is 2.4 GHz only (`band=bg`). Reached the box meanwhile over Ethernet (`nocs.local`). To decide: what the user guide (hardware, troubleshooting) says about USB 3 next to the Pi, and whether the access point should offer 5 GHz | To act on |
| night | First run (box setup) | After the setup (country Chile, the access point's password `nocsnocs` again, the home Wi-Fi), **every visit asked for the setup again**, though the box had joined the home network. The app took the first run as undone while the access point kept the default password (`ap_default_password`); keeping `nocsnocs` is a valid choice (maintainer). Now nocs-system records `set_up` when the owner sets the access point, and the app asks only while it is false; `ap_default_password` only drives Rig → Network's warning | **Fixed** on the branch, not yet in `main` |
