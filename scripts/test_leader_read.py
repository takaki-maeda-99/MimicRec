"""Directly test SO leader read_action() to see what error (if any) is being swallowed.

Usage:
    .venv/bin/python scripts/test_leader_read.py
    .venv/bin/python scripts/test_leader_read.py --port /dev/ttyACM1 --id my_awesome_leader_arm
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import traceback


def _check_no_active_session() -> None:
    """Refuse to run if MimicRec backend has an active session holding the ports."""
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
        # Backend not running or unreachable — that's fine for diagnostics
        pass


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="/dev/ttyACM1")
    parser.add_argument("--id", default="my_awesome_leader_arm")
    parser.add_argument("--ticks", type=int, default=20)
    parser.add_argument("--interval", type=float, default=0.05, help="seconds between reads")
    parser.add_argument("--wait", action="store_true", help="prompt before reading so you can prepare")
    args = parser.parse_args()

    _check_no_active_session()

    from mimicrec.adapters.so_leader import SOLeaderAdapter

    adapter = SOLeaderAdapter(port=args.port, id=args.id)
    print(f"Connecting to {args.port} (id={args.id}) ...")
    try:
        await adapter.connect()
    except Exception:
        print("CONNECT FAILED:")
        traceback.print_exc()
        return 1
    if args.wait:
        input("Press ENTER when ready (start moving the arm AFTER pressing Enter)...")

    print("Connected. Reading actions...\n")

    ok = 0
    fail = 0
    last_err = None
    first_pos = None
    max_delta = 0.0
    for i in range(args.ticks):
        try:
            action = await adapter.read_action()
            if action.target_joint_pos is None:
                print(f"  tick {i}: target_joint_pos=None")
                fail += 1
            else:
                pos = action.target_joint_pos
                if first_pos is None:
                    first_pos = pos.copy()
                else:
                    delta = float(((pos - first_pos) ** 2).sum() ** 0.5)
                    if delta > max_delta:
                        max_delta = delta
                print(f"  tick {i}: pos = " + ", ".join(f"{v:+7.2f}" for v in pos))
                ok += 1
        except Exception as e:
            fail += 1
            last_err = e
            print(f"  tick {i}: EXC {type(e).__name__}: {e}")
        await asyncio.sleep(args.interval)
    print(f"\nMax movement from first reading: {max_delta:.2f} (deg L2)")

    await adapter.disconnect()
    print(f"\nResult: ok={ok} fail={fail}")
    if last_err is not None:
        print("Last exception traceback:")
        traceback.print_exception(type(last_err), last_err, last_err.__traceback__)
    return 0 if ok > 0 and fail == 0 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
