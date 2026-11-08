import asyncio
import base64
import os
import threading
import zlib
from collections.abc import Callable

import pytest

from nocs.indi import protocol
from nocs.indi.client import IndiClient, PropertyUpdated
from nocs.indi.properties import (
    BlobElement,
    NumberElement,
    Permission,
    PropertyState,
    PropertyType,
    SwitchRule,
)
from nocs.indi.protocol import (
    BlobMode,
    DefineProperty,
    DeleteProperty,
    Message,
    ProtocolError,
    SetProperty,
    StreamParser,
    apply_set,
    decode_blob,
    encode_enable_blob,
    encode_get_properties,
    encode_new_vector,
    parse_number,
)

DEF_SWITCH = b"""<defSwitchVector device="CCD Simulator" name="CONNECTION" label="Connection"
 group="Main Control" state="Idle" perm="rw" rule="OneOfMany" timeout="60"
 timestamp="2026-10-27T22:00:00">
    <defSwitch name="CONNECT" label="Connect">Off</defSwitch>
    <defSwitch name="DISCONNECT" label="Disconnect">On</defSwitch>
</defSwitchVector>
"""

DEF_NUMBER = b"""<defNumberVector device="Telescope Simulator" name="EQUATORIAL_EOD_COORD"
 label="Eq. Coordinates" group="Main Control" state="Ok" perm="rw" timeout="60">
    <defNumber name="RA" label="RA (hh:mm:ss)" format="%010.6m" min="0" max="24" step="0">
      5:30:00
    </defNumber>
    <defNumber name="DEC" label="DEC (dd:mm:ss)" format="%010.6m" min="-90" max="90" step="0">
      -12.5
    </defNumber>
</defNumberVector>
"""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12.5", 12.5),
        ("  3 ", 3.0),
        ("", 0.0),
        ("5:30:00", 5.5),
        ("-0:30:00", -0.5),
        ("-12:30", -12.5),
        ("1 30 36", 1.51),
    ],
)
def test_parse_number(text: str, expected: float) -> None:
    assert parse_number(text) == pytest.approx(expected)


def test_parse_number_rejects_garbage() -> None:
    with pytest.raises(ProtocolError):
        parse_number("abc")


def test_define_switch_vector() -> None:
    [msg] = StreamParser().feed(DEF_SWITCH)
    assert isinstance(msg, DefineProperty)
    prop = msg.property
    assert prop.key == ("CCD Simulator", "CONNECTION")
    assert prop.type is PropertyType.SWITCH
    assert prop.rule is SwitchRule.ONE_OF_MANY
    assert prop.perm is Permission.READ_WRITE
    assert prop.timeout == 60
    assert not prop.switch("CONNECT")
    assert prop.switch("DISCONNECT")


def test_define_number_vector_with_sexagesimal_value() -> None:
    [msg] = StreamParser().feed(DEF_NUMBER)
    assert isinstance(msg, DefineProperty)
    ra = msg.property.elements["RA"]
    assert isinstance(ra, NumberElement)
    assert ra.value == pytest.approx(5.5)
    assert (ra.min, ra.max, ra.format) == (0, 24, "%010.6m")
    assert msg.property.number("DEC") == pytest.approx(-12.5)


def test_stream_split_at_arbitrary_points() -> None:
    data = DEF_SWITCH + DEF_NUMBER + b'<message device="CCD Simulator" message="hello"/>'
    parser = StreamParser()
    messages = [m for i in range(0, len(data), 7) for m in parser.feed(data[i : i + 7])]
    assert [type(m) for m in messages] == [DefineProperty, DefineProperty, Message]


def test_set_vector_updates_values_and_state() -> None:
    parser = StreamParser()
    [define] = parser.feed(DEF_NUMBER)
    assert isinstance(define, DefineProperty)
    [update] = parser.feed(
        b'<setNumberVector device="Telescope Simulator" name="EQUATORIAL_EOD_COORD" '
        b'state="Busy"><oneNumber name="RA">6.25</oneNumber></setNumberVector>'
    )
    assert isinstance(update, SetProperty)
    changed = apply_set(define.property, update)
    assert changed == ["RA"]
    assert define.property.state is PropertyState.BUSY
    assert define.property.number("RA") == 6.25
    assert define.property.number("DEC") == pytest.approx(-12.5)


def test_set_blob_decodes_compressed_payload() -> None:
    parser = StreamParser()
    [define] = parser.feed(
        b'<defBLOBVector device="CCD Simulator" name="CCD1" state="Idle" perm="ro">'
        b'<defBLOB name="CCD1" label="Image"/></defBLOBVector>'
    )
    assert isinstance(define, DefineProperty)
    payload = b"SIMPLE  =                    T" * 100
    encoded = base64.encodebytes(zlib.compress(payload))
    [update] = parser.feed(
        b'<setBLOBVector device="CCD Simulator" name="CCD1" state="Ok">'
        b'<oneBLOB name="CCD1" size="'
        + str(len(payload)).encode()
        + b'" format=".fits.z">'
        + encoded
        + b"</oneBLOB></setBLOBVector>"
    )
    assert isinstance(update, SetProperty)
    apply_set(define.property, update)
    blob = define.property.elements["CCD1"]
    assert isinstance(blob, BlobElement)
    assert blob.data == payload
    assert blob.size == len(payload)


DEF_BLOB = (
    b'<defBLOBVector device="Guide Simulator" name="CCD1" state="Idle" perm="ro">'
    b'<defBLOB name="CCD1" label="Image"/></defBLOBVector>\n'
)


def set_blob(payload: bytes, encoded: bytes) -> bytes:
    return (
        b'<setBLOBVector device="Guide Simulator" name="CCD1" state="Ok">'
        b'<oneBLOB name="CCD1" size="'
        + str(len(payload)).encode()
        + b'" format=".fits">\n'
        + encoded
        + b"\n</oneBLOB></setBLOBVector>\n"
    )


@pytest.mark.parametrize("encode", [base64.b64encode, base64.encodebytes], ids=["line", "lines"])
def test_blobs_decode_in_slices(encode: Callable[[bytes], bytes]) -> None:
    payload = os.urandom(300_001)  # several slices, and padding at the end
    assert decode_blob(encode(payload).decode(), ".fits") == payload
    assert decode_blob("", ".fits") == b""


def test_blobs_are_decoded_while_parsing() -> None:
    payload = os.urandom(100_000)
    parser = StreamParser()
    [define] = parser.feed(DEF_BLOB)
    message = set_blob(payload, base64.b64encode(payload))
    assert parser.feed(message[:70_000]) == []
    assert parser.unfinished == 70_000
    [update] = parser.feed(message[70_000:])
    assert parser.unfinished == 0
    assert isinstance(update, SetProperty)
    assert isinstance(define, DefineProperty)
    assert update.values["CCD1"].text == ""
    assert update.values["CCD1"].data == payload
    apply_set(define.property, update)
    blob = define.property.elements["CCD1"]
    assert isinstance(blob, BlobElement)
    assert blob.data == payload


async def test_large_blobs_are_decoded_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A guide frame's 3.5 MB of base64 would hold the event loop up (ADR 0012)."""
    payload = os.urandom(2_000_000)
    decoded_in: list[threading.Thread] = []

    def decode(text: str, fmt: str) -> bytes:
        decoded_in.append(threading.current_thread())
        return decode_blob(text, fmt)

    monkeypatch.setattr(protocol, "decode_blob", decode)

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(1000)  # getProperties
        writer.write(DEF_BLOB + set_blob(payload, base64.b64encode(payload)))
        await writer.drain()
        await reader.read(1000)

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    client = IndiClient("127.0.0.1", server.sockets[0].getsockname()[1])
    received: asyncio.Future[PropertyUpdated] = asyncio.get_running_loop().create_future()

    def on_event(event: object) -> None:
        if isinstance(event, PropertyUpdated) and not received.done():
            received.set_result(event)

    client.add_listener(on_event)
    try:
        await client.connect()
        event = await asyncio.wait_for(received, 10)
    finally:
        await client.close()
        server.close()
    assert isinstance(event, PropertyUpdated)
    blob = event.property.elements["CCD1"]
    assert isinstance(blob, BlobElement)
    assert blob.data == payload
    assert decoded_in
    assert threading.main_thread() not in decoded_in


def test_delete_property() -> None:
    [msg] = StreamParser().feed(b'<delProperty device="CCD Simulator" name="CCD_TEMPERATURE"/>')
    assert msg == DeleteProperty("CCD Simulator", "CCD_TEMPERATURE", None, None)


def test_unknown_elements_are_ignored() -> None:
    assert StreamParser().feed(b'<getProperties version="1.7"/>') == []


def test_malformed_xml_raises() -> None:
    with pytest.raises(ProtocolError):
        StreamParser().feed(b"<defSwitchVector></oops>")


def test_encode_new_switch_vector() -> None:
    data = encode_new_vector(
        PropertyType.SWITCH, "CCD Simulator", "CONNECTION", {"CONNECT": True, "DISCONNECT": False}
    )
    assert data == (
        b'<newSwitchVector device="CCD Simulator" name="CONNECTION">'
        b'<oneSwitch name="CONNECT">On</oneSwitch>'
        b'<oneSwitch name="DISCONNECT">Off</oneSwitch></newSwitchVector>\n'
    )


def test_encode_escapes_text() -> None:
    data = encode_new_vector(PropertyType.TEXT, "Dev & Co", "NAME", {"V": "<a>"})
    assert b'device="Dev &amp; Co"' in data
    assert b"&lt;a&gt;" in data


def test_encode_rejects_light_vectors() -> None:
    with pytest.raises(ValueError, match="cannot send"):
        encode_new_vector(PropertyType.LIGHT, "d", "n", {"x": True})


def test_encode_get_properties_and_enable_blob() -> None:
    assert encode_get_properties() == b'<getProperties version="1.7" />\n'
    assert encode_enable_blob("CCD Simulator", BlobMode.ALSO) == (
        b'<enableBLOB device="CCD Simulator">Also</enableBLOB>\n'
    )
