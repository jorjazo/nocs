# INDI recordings

Raw INDI protocol XML captured from real devices with
[`dev/tools/indi_record.py`](../tools/indi_record.py): every property the drivers
define (twice: once per connection of the recorder) and the updates that followed
for ~15 s. No BLOBs. Used to write device facades and to feed fake servers in
tests for hardware that has no INDI simulator.

| File | Devices | Notes |
|---|---|---|
| `lab-rig-2026-10-30.xml` | ZWO ASI2600MC Duo (+ its ASI220MM Mini guide sensor), ZWO EAF, ZWO EFW (8 slots), ZWO AM5, Pegasus PPBA Gen2 | INDI 2.2.5 from the PPA on the lab Pi 5, all devices connected through nocsd (cameras already pointed at the rig with `ACTIVE_DEVICES`). The PPBA driver also defines five empty vectors (`device=""`). |
