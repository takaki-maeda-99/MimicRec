"""Standalone probe: ask the GoPro to start its preview stream and listen
for raw UDP bytes on the requested port. No pyav, no CameraManager — just
verifies whether the GoPro actually emits to the host.

Run AFTER stopping the MimicRec session (so the preview port is free).

Usage:
    # HERO9–11 always emit to UDP 8554 regardless of the port arg.
    .venv/bin/python scripts/gopro_preview_probe.py

    # HERO12/13 honor the port arg.
    .venv/bin/python scripts/gopro_preview_probe.py --port 18556
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("probe")


async def main(port: int, listen_seconds: int) -> int:
    try:
        from open_gopro import WiredGoPro
        from open_gopro.models import constants
    except ImportError as e:
        log.error("open_gopro not installed in this venv: %s", e)
        return 2

    log.info("opening WiredGoPro (auto-discover serial)")
    async with WiredGoPro() as gopro:
        log.info("wired-USB control ENABLE")
        await gopro.http_command.wired_usb_control(control=constants.Toggle.ENABLE)

        log.info("preflight: set_preview_stream DISABLE")
        try:
            r = await gopro.http_command.set_preview_stream(mode=constants.Toggle.DISABLE)
            log.info("preflight DISABLE response ok=%s", getattr(r, "ok", "?"))
        except Exception as e:
            log.info("preflight DISABLE ignored: %s", e)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        sock.bind(("0.0.0.0", port))
        sock.settimeout(0.5)
        log.info("UDP socket bound on 0.0.0.0:%d (SO_REUSEPORT, recv timeout 0.5s)", port)

        log.info("set_preview_stream ENABLE port=%d", port)
        r = await gopro.http_command.set_preview_stream(
            mode=constants.Toggle.ENABLE, port=port,
        )
        log.info("ENABLE response ok=%s status=%s",
                 getattr(r, "ok", "?"), getattr(r, "status", "?"))

        log.info("listening for UDP traffic for %ds...", listen_seconds)
        deadline = time.monotonic() + listen_seconds
        bytes_total = 0
        pkts = 0
        sources: dict[str, int] = {}
        first_packet_at: float | None = None
        try:
            while time.monotonic() < deadline:
                try:
                    data, addr = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                if first_packet_at is None:
                    first_packet_at = time.monotonic()
                    log.info("FIRST PACKET: %d bytes from %s:%d (head=%s)",
                             len(data), addr[0], addr[1],
                             data[:8].hex())
                bytes_total += len(data)
                pkts += 1
                key = f"{addr[0]}:{addr[1]}"
                sources[key] = sources.get(key, 0) + 1
        finally:
            try:
                await gopro.http_command.set_preview_stream(mode=constants.Toggle.DISABLE)
                log.info("preview stream DISABLED")
            except Exception as e:
                log.warning("teardown DISABLE failed: %s", e)
            sock.close()

        if pkts == 0:
            log.error(
                "TIMEOUT: zero UDP packets received on 0.0.0.0:%d during %ds. "
                "GoPro is not emitting to this port. Try --port 8554, or check "
                "host USB-Ethernet interface (ip -4 addr).",
                port, listen_seconds,
            )
            return 1

        log.info(
            "OK: %d packets / %d bytes from %s. First packet at +%.2fs.",
            pkts, bytes_total, sources, (first_packet_at or 0) - (deadline - listen_seconds),
        )
        return 0


def parse() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8554,
                   help="UDP port to listen on. HERO9–11 ignore the port arg "
                        "and always emit to 8554 (the OpenGoPro default). "
                        "HERO12/13 honor the port arg, so any unused port works.")
    p.add_argument("--seconds", type=int, default=10,
                   help="how long to listen for packets")
    return p.parse_args()


if __name__ == "__main__":
    args = parse()
    sys.exit(asyncio.run(main(args.port, args.seconds)))
