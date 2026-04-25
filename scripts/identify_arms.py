"""Identify which serial port has which SO-101 arm by polling positions.

Connects to both /dev/ttyACM0 and /dev/ttyACM1, reads joint positions every
~0.3s, and prints them. Move ONE arm by hand and watch which column changes
to identify which port has follower vs leader.

Usage:
    .venv/bin/python scripts/identify_arms.py
    .venv/bin/python scripts/identify_arms.py --ports /dev/ttyACM0 /dev/ttyACM1
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np


JOINT_NAMES = [
    "shoulder_pan", "shoulder_lift", "elbow_flex",
    "wrist_flex", "wrist_roll", "gripper",
]


def open_as_follower(port: str, cal_id: str | None):
    from lerobot.robots.so101_follower.so101_follower import SO101Follower
    from lerobot.robots.so101_follower.config_so101_follower import SO101FollowerConfig
    cfg = SO101FollowerConfig(port=port, id=cal_id or "")
    arm = SO101Follower(cfg)
    arm.connect(calibrate=False)
    return arm


def read_pos(arm) -> np.ndarray | None:
    try:
        obs = arm.get_observation()
        return np.array([obs[f"{j}.pos"] for j in JOINT_NAMES], dtype=np.float32)
    except Exception as e:
        return None


def _check_no_active_session() -> None:
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:8000/api/session/state", timeout=0.5) as r:
            import json
            data = json.loads(r.read())
        if data.get("state") and data["state"] != "idle":
            print(
                f"ERROR: MimicRec backend has an ACTIVE session (state={data['state']!r}). "
                f"It is holding the serial ports.\n"
                f"End the session first:\n"
                f"  curl -X POST http://localhost:8000/api/session/end\n",
                file=sys.stderr,
            )
            sys.exit(3)
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ports", nargs="+", default=["/dev/ttyACM0", "/dev/ttyACM1"])
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument("--cal", default="my_awesome_follower_arm",
                        help="Calibration id to attempt; falls back to no-cal if missing")
    args = parser.parse_args()

    _check_no_active_session()

    print(f"Opening {args.ports} ...")
    arms = {}
    for p in args.ports:
        try:
            arms[p] = open_as_follower(p, args.cal)
            print(f"  {p}: connected (as follower with cal={args.cal!r})")
        except Exception as e:
            try:
                arms[p] = open_as_follower(p, None)
                print(f"  {p}: connected without calibration")
            except Exception as e2:
                print(f"  {p}: FAILED to open: {e2}")

    if not arms:
        print("No ports opened. Exiting.")
        return 1

    print()
    print("Now move ONE arm by hand. The port whose values change is that arm.")
    print("Press Ctrl+C to stop.\n")
    print(f"{'time':>6}  " + "  ".join(f"{p:>14}" for p in arms))

    start = time.monotonic()
    try:
        while time.monotonic() - start < args.seconds:
            t = time.monotonic() - start
            cells = []
            for p, arm in arms.items():
                pos = read_pos(arm)
                if pos is None:
                    cells.append(f"{'<read err>':>14}")
                else:
                    # Show only first 3 joints for readability
                    cells.append(f"{pos[0]:+6.1f},{pos[1]:+6.1f}")
            print(f"{t:6.1f}  " + "  ".join(cells))
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        for p, arm in arms.items():
            try:
                arm.disconnect()
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
