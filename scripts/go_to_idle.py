#!/usr/bin/env python3
"""Move the arm smoothly to the configured idle pose.

Connects to the running rebotarm daemon, reads current state, and ramps
to ``configs/rebotarm/idle_pose.yaml`` over a configurable duration.

    .venv/bin/python scripts/go_to_idle.py
    .venv/bin/python scripts/go_to_idle.py --duration 5 --after gravity_comp
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from mimicrec.adapters.rebotarm_zmq import ReBotArmZmqAdapter
from mimicrec.adapters.robot import RobotMode
from mimicrec.session.idle import (
    DEFAULT_IDLE_POSE_PATH, load_idle_pose, move_to_idle,
)


async def _run(
    duration: float, fps: int, after: RobotMode, idle_path: Path
) -> None:
    idle_pose = load_idle_pose(idle_path)
    adapter = ReBotArmZmqAdapter()
    await adapter.connect()
    try:
        await move_to_idle(
            adapter,
            idle_pose=idle_pose,
            duration_sec=duration,
            fps=fps,
            after_mode=after,
        )
    finally:
        await adapter.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=3.0,
                        help="seconds to ramp from current pose to idle (default: 3.0)")
    parser.add_argument("--fps", type=int, default=30,
                        help="setpoint rate during the ramp (default: 30)")
    parser.add_argument("--after", choices=["position", "gravity_comp"],
                        default="position",
                        help="mode to leave the arm in after arrival "
                             "(default: position = hold idle)")
    parser.add_argument("--idle-path", type=Path, default=DEFAULT_IDLE_POSE_PATH,
                        help=f"path to idle pose yaml (default: {DEFAULT_IDLE_POSE_PATH})")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(_run(
        duration=args.duration,
        fps=args.fps,
        after=RobotMode(args.after),
        idle_path=args.idle_path,
    ))


if __name__ == "__main__":
    main()
