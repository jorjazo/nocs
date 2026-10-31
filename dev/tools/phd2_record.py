"""Record PHD2's event stream as JSON lines, for tests and UI work.

Listens to PHD2's event server and saves every event it sends (answers to calls
are not events, and this client makes none) until the time is up or it is
interrupted. Drive PHD2 meanwhile from NOCS, PHD2's own window or a script: the
recording keeps calibration, guide steps, dithers and settling as PHD2 sent them.

Typical use against the dev containers, while a guiding session runs:

    uv run --project server python dev/tools/phd2_record.py --seconds 180 \\
        -o dev/recordings/phd2-simulators.jsonl

Usage: uv run --project server python dev/tools/phd2_record.py [options] -o <file>
"""

import argparse
import asyncio
import contextlib
import json
import sys
import time
from pathlib import Path


async def record(host: str, port: int, out: Path, seconds: float) -> int:
    reader, writer = await asyncio.open_connection(host, port, limit=2**20)
    count = 0
    deadline = time.monotonic() + seconds
    with out.open("w", buffering=1) as f:  # line by line: nothing lost if killed
        try:
            while (left := deadline - time.monotonic()) > 0:
                try:
                    line = await asyncio.wait_for(reader.readline(), left)
                except TimeoutError:
                    break
                if not line:
                    print("PHD2 closed the connection", file=sys.stderr)
                    break
                event = json.loads(line)
                if "Event" not in event:
                    continue
                f.write(json.dumps(event, separators=(",", ":")) + "\n")
                count += 1
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=4400)
    parser.add_argument("--seconds", type=float, default=120.0)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        count = asyncio.run(record(args.host, args.port, args.output, args.seconds))
        print(f"{count} events written to {args.output}")


if __name__ == "__main__":
    main()
