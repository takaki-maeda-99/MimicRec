"""Daemon CLI entry: ``python -m rebotarm_daemon --config <path>``."""
from __future__ import annotations

import argparse
import sys

from rebotarm_daemon.config import load_daemon_config
from rebotarm_daemon.server import run_server


def main() -> int:
    parser = argparse.ArgumentParser(
        description="reBotArm safety daemon (Python 3.10, real hardware)",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the daemon YAML config (see configs/rebotarm/*.yaml).",
    )
    args = parser.parse_args()
    cfg = load_daemon_config(args.config)
    run_server(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
