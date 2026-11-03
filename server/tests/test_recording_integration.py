"""Recording a session of the INDI simulators (ADR 0038; see conftest.indi_address)."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from nocs.devices import Device
from nocs.indi import IndiClient, PropertyState
from nocs.indi.recording import Recorder, read

pytestmark = pytest.mark.indi

FOCUSER = "Focuser Simulator"


async def test_records_a_focuser_move(indi_address: tuple[str, int], tmp_path: Path) -> None:
    recorder = Recorder(*indi_address, tmp_path / "focuser.zip", devices=[FOCUSER])
    await recorder.start()
    async with IndiClient(*indi_address) as client:
        await Device(client, FOCUSER).connect()
        position = await client.wait_for_property(FOCUSER, "ABS_FOCUS_POSITION")
        target = 31000.0 if position.number("FOCUS_ABSOLUTE_POSITION") != 31000 else 29000.0
        await client.send(FOCUSER, "ABS_FOCUS_POSITION", {"FOCUS_ABSOLUTE_POSITION": target})
        await client.wait_for(
            lambda _: (
                position.state is PropertyState.OK
                and position.number("FOCUS_ABSOLUTE_POSITION") == target
            ),
            timeout=30,
        )
    await recorder.stop()

    recording = read(recorder.path)
    assert recording.manifest["recorded"] == [FOCUSER]
    drivers = recording.manifest["drivers"]
    assert isinstance(drivers, dict)
    driver = drivers[FOCUSER]
    assert isinstance(driver, dict)
    assert driver["exec"] == "indi_simulator_focus"
    messages = [(m.command, ET.fromstring(m.xml)) for m in recording.messages]
    assert messages[0][1].tag.startswith("def")
    # The other client's command, echoed by indiserver, then the driver's answers.
    moves = [
        i
        for i, (command, elem) in enumerate(messages)
        if command and elem.get("name") == "ABS_FOCUS_POSITION"
    ]
    assert len(moves) == 1
    answers = [
        elem
        for command, elem in messages[moves[0] :]
        if not command
        and elem.tag == "setNumberVector"
        and elem.get("name") == "ABS_FOCUS_POSITION"
    ]
    assert answers[-1].get("state") == "Ok"
    assert float((answers[-1][0].text or "").strip()) == target
