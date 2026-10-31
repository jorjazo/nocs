"""A fake indiserver with one recorded Pegasus PPBA, to try the power box UI without one.

There is no INDI simulator for power boxes. This serves what the lab's PPBA
defined (``dev/recordings/lab-rig-2026-10-30.xml``) and answers new values as
``indi_pegasus_ppba`` 1.4 does: ``Ok`` with the values, elements of its power
interface matched by position (INDI 2.2.5), duty cycles back from the 0-255
scale (and at 0 for a dew channel switched off) and the input current wandering every two seconds.

Point a nocsd at it with a profile whose power and weather roles name the
driver ``indi_pegasus_ppba`` (the device is adopted, not started):

    uv run --project server python dev/tools/fake_ppba.py --port 7625
    NOCS_INDI_PORT=7625 uv run --project server nocsd

Usage: uv run --project server python dev/tools/fake_ppba.py [--port 7625]
"""

import argparse
import asyncio
import contextlib
import random
import xml.etree.ElementTree as ET
from pathlib import Path

RECORDING = Path(__file__).resolve().parents[1] / "recordings" / "lab-rig-2026-10-30.xml"
DEVICE = "Pegasus PPBA"
POSITIONAL = {"POWER_CHANNELS", "DEW_CHANNELS", "AUTO_DEW_CONTROL", "DEW_DUTY_CYCLES"}


def load() -> dict[str, ET.Element]:
    root = ET.fromstring(b"<indi>" + RECORDING.read_bytes() + b"</indi>")
    definitions: dict[str, ET.Element] = {}
    for element in root:
        name = element.get("name")
        if element.tag.startswith("def") and element.get("device") == DEVICE and name:
            definitions.setdefault(name, element)
    return definitions


class FakePpba:
    def __init__(self) -> None:
        self.properties = load()
        self.clients: set[asyncio.StreamWriter] = set()

    def update(self, name: str, state: str = "Ok") -> bytes:
        definition = self.properties[name]
        kind = definition.tag.removeprefix("def")  # e.g. "SwitchVector"
        member = kind.removesuffix("Vector")
        update = ET.Element(f"set{kind}", device=DEVICE, name=name, state=state)
        for child in definition:
            ET.SubElement(update, f"one{member}", name=child.get("name", "")).text = child.text
        definition.set("state", state)
        return ET.tostring(update) + b"\n"

    def apply(self, message: ET.Element) -> bytes | None:
        name = message.get("name", "")
        if message.get("device") != DEVICE or name not in self.properties:
            return None
        definition = self.properties[name]
        children = list(definition)
        sent = [(c.get("name", ""), (c.text or "").strip()) for c in message]
        if name in POSITIONAL:
            pairs = [(children[i], value) for i, (_, value) in enumerate(sent) if i < len(children)]
        else:
            by_name = {c.get("name"): c for c in children}
            pairs = [(by_name[n], value) for n, value in sent if n in by_name]
        if definition.get("rule") == "OneOfMany" and any(v == "On" for _, v in pairs):
            for child in children:
                child.text = "Off"
        for child, value in pairs:
            if name == "DEW_DUTY_CYCLES":
                value = str(int(float(value) / 100 * 255) / 255 * 100)
            child.text = value
        reply = self.update(name)
        if name == "DEW_CHANNELS":
            # A channel switched off gets PWM 0, and reads back at 0 %.
            duties = list(self.properties["DEW_DUTY_CYCLES"])
            for channel, duty in zip(children, duties, strict=False):
                if (channel.text or "").strip() == "Off":
                    duty.text = "0"
            reply += self.update("DEW_DUTY_CYCLES")
        return reply

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.clients.add(writer)
        parser = ET.XMLPullParser(events=("start", "end"))
        parser.feed(b"<stream>")
        depth = 0
        try:
            while data := await reader.read(4096):
                parser.feed(data)
                for event, element in parser.read_events():
                    depth += 1 if event == "start" else -1
                    if event != "end" or depth != 1:
                        continue
                    if element.tag == "getProperties":
                        for definition in self.properties.values():
                            writer.write(ET.tostring(definition) + b"\n")
                    elif element.tag.startswith("new") and (reply := self.apply(element)):
                        self.broadcast(reply)
                await writer.drain()
        finally:
            self.clients.discard(writer)
            writer.close()

    def broadcast(self, data: bytes) -> None:
        for writer in list(self.clients):
            writer.write(data)

    async def wander(self) -> None:
        sensors = self.properties["POWER_SENSORS"]
        while True:
            await asyncio.sleep(2)
            for child in sensors:
                if child.get("name") == "SENSOR_CURRENT":
                    child.text = f"{1.2 + random.uniform(-0.1, 0.1):.3f}"
            self.broadcast(self.update("POWER_SENSORS"))


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7625)
    args = parser.parse_args()
    fake = FakePpba()
    server = await asyncio.start_server(fake.serve, args.host, args.port)
    print(f"fake {DEVICE} on {args.host}:{args.port}", flush=True)
    async with server:
        await asyncio.gather(server.serve_forever(), fake.wander())


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
