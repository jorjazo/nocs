# INDI recordings

Raw INDI protocol XML captured from real devices with
[`dev/tools/indi_record.py`](../tools/indi_record.py): every property the drivers
define (twice: once per connection of the recorder) and the updates that followed
for ~15 s. No BLOBs. Used to write device facades and to feed fake servers in
tests for hardware that has no INDI simulator (`FakeClient.replay` in the
server tests; [`dev/tools/fake_ppba.py`](../tools/fake_ppba.py) serves the PPBA
to a nocsd).

| File | Devices | Notes |
|---|---|---|
| `lab-rig-2026-10-30.xml` | ZWO ASI2600MC Duo (+ its ASI220MM Mini guide sensor), ZWO EAF, ZWO EFW (8 slots), ZWO AM7 (its driver, `indi_lx200am5`, names the device "ZWO AM5"), Pegasus PPBA Gen2 | INDI 2.2.5 from the PPA on the lab Pi 5, all devices connected through nocsd (cameras already pointed at the rig with `ACTIVE_DEVICES`). The PPBA driver also defines five empty vectors (`device=""`). |

## PHD2 recordings

PHD2's event stream as JSON lines, captured with
[`dev/tools/phd2_record.py`](../tools/phd2_record.py). Used to test the guiding
statistics and to work on the guiding UI without a sky.

| File | Session | Notes |
|---|---|---|
| `phd2-simulators-2026-10-31.jsonl` | PHD2 2.6.14 headless with the INDI simulators: Guide Simulator (2.4 µm) at 120 mm, 4.13″/px, Telescope Simulator at RA 5.6 h, Dec −5.4° | 1 s exposures: calibration (41 steps), guiding with settling, a 5 px dither and its settling, guiding, stop. 131 events over ~3 min. |
