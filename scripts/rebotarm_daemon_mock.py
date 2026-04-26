#!/usr/bin/env python
"""Mock reBotArm safety daemon for tests / dev without hardware.

Speaks the same ZMQ wire protocol as the real daemon. Synthesizes a slow
sinusoidal joint trajectory so /ws/state plots have signal. Implements
the estop / clear_estop / heartbeat / safety_status semantics so
integration tests can exercise them.

Usage:
    .venv/bin/python scripts/rebotarm_daemon_mock.py
    .venv/bin/python scripts/rebotarm_daemon_mock.py --port 5599
"""
from __future__ import annotations

import argparse
import math
import signal
import sys
import time

import numpy as np
import zmq

from mimicrec.adapters.rebotarm_protocol import (
    CMD_CONNECT, CMD_DISCONNECT, CMD_READ_STATE, CMD_SEND_COMMAND,
    CMD_SET_MODE, CMD_HEARTBEAT, CMD_ESTOP, CMD_CLEAR_ESTOP,
    CMD_GET_SAFETY_STATUS, MODE_POSITION, MODE_GRAVITY_COMP,
    SAFETY_OK, SAFETY_ESTOP,
)


JOINT_NAMES = [f"j{i}" for i in range(1, 7)]
DOF = 6


def _make_payload(t0: float) -> dict:
    t = time.monotonic() - t0
    q = np.array([0.3 * math.sin(t * 0.5 + i * 0.7) for i in range(DOF)], dtype=np.float32)
    qd = np.array([0.15 * math.cos(t * 0.5 + i * 0.7) for i in range(DOF)], dtype=np.float32)
    return {
        "joint_pos": q.tolist(),
        "joint_vel": qd.tolist(),
        "joint_effort": [0.0] * DOF,
        "ee_pos": [0.20 + 0.05 * math.sin(t), 0.10 + 0.02 * math.cos(t), 0.30],
        "ee_rotvec": [0.0, 0.0, 0.5 * math.sin(t * 0.3)],
        "gripper_pos": float(50 + 30 * math.sin(t * 0.4)),
        "motor_temps_c": [40.0] * DOF,
        "motor_torques_nm": [0.05] * DOF,
        "t_mono_ns": time.monotonic_ns(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5558)
    args = parser.parse_args()

    ctx = zmq.Context()
    sock = ctx.socket(zmq.REP)
    sock.bind(f"tcp://*:{args.port}")
    sock.setsockopt(zmq.RCVTIMEO, 100)

    state = {
        "connected": False,
        "mode": MODE_GRAVITY_COMP,
        "fault": None,           # None | "estop" | "thermal_fault"
        "last_hb": 0.0,
        "last_cmd_q": None,
        "t0": time.monotonic(),
    }

    print(f"[mock-daemon] listening on tcp://*:{args.port}")
    stopped = False

    def _stop(*_):
        nonlocal stopped
        stopped = True
        print("\n[mock-daemon] stopping")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    while not stopped:
        try:
            msg = sock.recv_json()
        except zmq.Again:
            continue
        except (ValueError, zmq.ZMQError) as e:
            # REP state machine requires a reply before the next recv,
            # otherwise the socket desyncs.
            try:
                sock.send_json({"ok": False, "error": f"bad request: {e}"})
            except zmq.ZMQError:
                pass
            continue
        if not isinstance(msg, dict):
            sock.send_json({"ok": False, "error": "request must be a JSON object"})
            continue
        cmd = msg.get("cmd")

        if cmd == CMD_CONNECT:
            state["connected"] = True
            state["t0"] = time.monotonic()
            sock.send_json({"ok": True, "dof": DOF, "joint_names": JOINT_NAMES,
                            "ee_frame": "tool0"})
        elif cmd == CMD_DISCONNECT:
            state["connected"] = False
            sock.send_json({"ok": True})
        elif cmd == CMD_HEARTBEAT:
            state["last_hb"] = time.monotonic()
            sock.send_json({"ok": True})
        elif cmd == CMD_READ_STATE:
            payload = _make_payload(state["t0"])
            payload["safety_state"] = state["fault"] or SAFETY_OK
            sock.send_json(payload)
        elif cmd == CMD_SEND_COMMAND:
            if state["fault"]:
                sock.send_json({"ok": False, "error": f"fault active: {state['fault']}"})
            else:
                state["last_cmd_q"] = msg.get("q", [])
                sock.send_json({"ok": True})
        elif cmd == CMD_SET_MODE:
            m = msg.get("mode", MODE_GRAVITY_COMP)
            # Validate to match the real daemon's behavior so misuse is
            # caught in integration tests.
            if m not in (MODE_POSITION, MODE_GRAVITY_COMP):
                sock.send_json({"ok": False, "error": f"unknown mode: {m}"})
            else:
                state["mode"] = m
                sock.send_json({"ok": True, "mode": m})
        elif cmd == CMD_ESTOP:
            state["fault"] = SAFETY_ESTOP
            sock.send_json({"ok": True})
        elif cmd == CMD_CLEAR_ESTOP:
            # always succeeds in mock (no real temp / heartbeat constraints)
            state["fault"] = None
            sock.send_json({"ok": True})
        elif cmd == CMD_GET_SAFETY_STATUS:
            sock.send_json({
                "safety_state": state["fault"] or SAFETY_OK,
                "mode": state["mode"],
            })
        else:
            sock.send_json({"ok": False, "error": f"unknown cmd: {cmd}"})

    sock.close(linger=0)
    ctx.term()
    return 0


if __name__ == "__main__":
    sys.exit(main())
