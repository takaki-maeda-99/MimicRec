#!/usr/bin/env python3
"""Fail unless a TCP port is available for a managed service to bind."""
from __future__ import annotations

import argparse
import socket


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("0.0.0.0", args.port))
        except OSError as exc:
            parser.error(f"TCP port {args.port} is already in use: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
