#!/usr/bin/env python
"""Calibrate an SO-101 follower or leader arm via LeRobot's interactive flow.

Usage:
    python scripts/calibrate_so101.py --port /dev/ttyACM0 --id my_follower --type follower
    python scripts/calibrate_so101.py --port /dev/ttyACM1 --id my_leader --type leader

This runs LeRobot's interactive calibration which will:
1. Ask you to move the arm to the middle of its range
2. Ask you to move each joint through its full range
3. Save a calibration file to ~/.cache/huggingface/lerobot/calibration/

After calibration, the id you chose here must match the 'id' field in
your MimicRec config YAML (e.g. configs/robot/so101.yaml).
"""
import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Calibrate SO-101 arm")
    parser.add_argument("--port", required=True, help="Serial port (e.g. /dev/ttyACM0)")
    parser.add_argument("--id", required=True, help="Arm identifier for calibration file")
    parser.add_argument("--type", required=True, choices=["follower", "leader"],
                        help="follower or leader arm")
    parser.add_argument("--force", action="store_true",
                        help="Delete existing calibration file before running, forcing a fresh calibration")
    args = parser.parse_args()

    if args.force:
        # LeRobot resolves cal path as: HF_LEROBOT_CALIBRATION / {ROBOTS|TELEOPERATORS} / <self.name> / <id>.json
        # SO101Follower.name == "so_follower", SOLeader.name == "so_leader"
        sub = "robots/so_follower" if args.type == "follower" else "teleoperators/so_leader"
        cal_path = Path.home() / ".cache/huggingface/lerobot/calibration" / sub / f"{args.id}.json"
        if cal_path.exists():
            cal_path.unlink()
            print(f"Deleted existing calibration: {cal_path}")
        else:
            print(f"No existing calibration at {cal_path} (proceeding fresh)")

    if args.type == "follower":
        from lerobot.robots.so_follower.so_follower import SO101Follower
        from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig
        cfg = SOFollowerRobotConfig(port=args.port, id=args.id)
        arm = SO101Follower(cfg)
        print(f"Calibrating SO-101 FOLLOWER on {args.port} (id={args.id})")
        arm.connect(calibrate=True)
        arm.disconnect()
    else:
        from lerobot.teleoperators.so_leader.so_leader import SOLeader
        from lerobot.teleoperators.so_leader.config_so_leader import SOLeaderTeleopConfig
        cfg = SOLeaderTeleopConfig(port=args.port, id=args.id)
        arm = SOLeader(cfg)
        print(f"Calibrating SO-101 LEADER on {args.port} (id={args.id})")
        arm.connect(calibrate=True)
        arm.disconnect()

    print(f"\nCalibration saved. Use id='{args.id}' in your MimicRec config YAML.")


if __name__ == "__main__":
    main()
