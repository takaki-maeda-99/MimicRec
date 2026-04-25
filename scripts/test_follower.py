"""Diagnose SO-101 follower: read state and (optionally) attempt a tiny actuation.

Phase 1 (always): connect, read positions for N ticks, disconnect.
    Looks for: voltage errors, packet errors, dropouts in sync_read.

Phase 2 (with --actuate): attempt a small +/- 3 degree wiggle on shoulder_pan,
    then return to start. Looks for: motor actuation under load.

Usage:
    .venv/bin/python scripts/test_follower.py --port /dev/ttyACM2 --id my_awesome_follower_arm
    .venv/bin/python scripts/test_follower.py --port /dev/ttyACM2 --id my_awesome_follower_arm --actuate
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
import traceback


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


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="/dev/ttyACM2")
    parser.add_argument("--id", default="my_awesome_follower_arm")
    parser.add_argument("--ticks", type=int, default=30)
    parser.add_argument("--interval", type=float, default=0.1)
    parser.add_argument("--actuate", action="store_true",
                        help="Phase 2: send a small Goal_Position command and check if it moves")
    parser.add_argument("--actuate-deg", type=float, default=3.0,
                        help="Magnitude of test motion in motor units")
    args = parser.parse_args()

    _check_no_active_session()

    from mimicrec.adapters.so101 import SO101Adapter

    adapter = SO101Adapter(port=args.port, id=args.id)
    print(f"Connecting follower {args.port} (id={args.id}) ...")
    try:
        await adapter.connect()
    except Exception:
        print("CONNECT FAILED:")
        traceback.print_exc()
        return 1
    print("Connected.\n")

    # ---- Phase 1: read state ----
    print(f"--- Phase 1: read state x {args.ticks} ---")
    ok = 0
    fail = 0
    last_err = None
    initial_pos = None
    for i in range(args.ticks):
        try:
            state = await adapter.read_state()
            if initial_pos is None:
                initial_pos = state.joint_pos.copy()
            print(f"  tick {i}: pos = " + ", ".join(f"{v:+7.2f}" for v in state.joint_pos))
            ok += 1
        except Exception as e:
            fail += 1
            last_err = e
            print(f"  tick {i}: EXC {type(e).__name__}: {e}")
        await asyncio.sleep(args.interval)
    print(f"Phase 1 result: ok={ok} fail={fail}")
    if last_err is not None:
        print("Last exception traceback:")
        traceback.print_exception(type(last_err), last_err, last_err.__traceback__)

    # ---- Phase 2: small actuation ----
    if args.actuate and initial_pos is not None:
        import numpy as np
        print(f"\n--- Phase 2: actuation (joint 0 ± {args.actuate_deg} deg) ---")
        target_a = initial_pos.copy()
        target_a[0] += args.actuate_deg
        target_b = initial_pos.copy()

        try:
            print(f"  sending +{args.actuate_deg} on joint 0 ...")
            await adapter.send_joint_command(target_a)
            await asyncio.sleep(1.0)
            mid = await adapter.read_state()
            print(f"  after +cmd: pos = " + ", ".join(f"{v:+7.2f}" for v in mid.joint_pos))
            moved = float(abs(mid.joint_pos[0] - initial_pos[0]))
            print(f"  joint 0 actually moved: {moved:.2f} deg (commanded {args.actuate_deg})")

            print(f"  returning to start ...")
            await adapter.send_joint_command(target_b)
            await asyncio.sleep(1.0)
            end = await adapter.read_state()
            print(f"  after return: pos = " + ", ".join(f"{v:+7.2f}" for v in end.joint_pos))
        except Exception as e:
            print(f"  ACTUATE FAILED: {type(e).__name__}: {e}")
            traceback.print_exc()

    # ---- Disconnect ----
    print("\n--- Disconnect ---")
    try:
        await adapter.disconnect()
        print("Clean disconnect.")
    except Exception as e:
        print(f"DISCONNECT FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()

    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
