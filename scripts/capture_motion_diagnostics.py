#!/usr/bin/env python3
"""Capture MimicRec's passive state WebSocket as timestamped JSONL."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import signal
import time

import websockets


async def capture(url: str, output: Path) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)

    output.parent.mkdir(parents=True, exist_ok=True)
    async with websockets.connect(url, max_size=None) as websocket:
        with output.open("a", encoding="utf-8", buffering=1) as stream:
            while not stop.is_set():
                try:
                    message = await asyncio.wait_for(
                        websocket.recv(), timeout=0.25
                    )
                except asyncio.TimeoutError:
                    continue
                payload = json.loads(message)
                row = {
                    "capture_t_mono_ns": time.monotonic_ns(),
                    "capture_t_wall_ns": time.time_ns(),
                    "state": payload,
                }
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8000/ws/state")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(capture(args.url, args.output))


if __name__ == "__main__":
    main()
