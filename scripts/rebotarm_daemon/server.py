"""ZMQ REP server for the reBotArm safety daemon.

This module is the only entry point that touches the real reBotArm SDK
(``motorbridge`` + ``reBotArm_control_py``) and therefore must run under
Python 3.10. CI cannot exercise it; the mock daemon at
``scripts/rebotarm_daemon_mock.py`` mirrors the wire protocol for the
3.12 backend tests.

Threading model
---------------
``RobotArm.start_control_loop(callback, rate=...)`` spawns a daemon
thread that calls ``callback(arm, dt)`` at the requested rate (verified
in actuator/arm.py:737). The main thread therefore drives the ZMQ REP
loop directly — no extra threading needed beyond the SDK's.

Wire-protocol constants are duplicated from
``backend/mimicrec/adapters/rebotarm_protocol.py`` because the daemon
runs in a separate venv and cannot import the backend package. Keep
them in sync.
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np
import zmq

from reBotArm_control_py.actuator import RobotArm

from rebotarm_daemon.config import DaemonConfig
from rebotarm_daemon.controllers import (
    GravityCompLockController,
    PositionController,
)
from rebotarm_daemon.ee_pose import EEPose
from rebotarm_daemon.safety import SafetyManager
from rebotarm_daemon.state import SharedRobotState


# ---------------------------------------------------------------------------
# Wire-protocol constants (intentionally duplicated from
# backend/mimicrec/adapters/rebotarm_protocol.py — daemon runs in a
# different venv and cannot import that module).
# ---------------------------------------------------------------------------
CMD_CONNECT = "connect"
CMD_DISCONNECT = "disconnect"
CMD_READ_STATE = "read_state"
CMD_SEND_COMMAND = "send_command"
CMD_SET_MODE = "set_mode"
CMD_HEARTBEAT = "heartbeat"
CMD_ESTOP = "estop"
CMD_CLEAR_ESTOP = "clear_estop"
CMD_GET_SAFETY_STATUS = "get_safety_status"

MODE_POSITION = "position"
MODE_GRAVITY_COMP = "gravity_comp"

SAFETY_OK = "ok"


def _switch_arm_mode(arm: RobotArm, target_mode: str, gravity_kp, gravity_kd) -> None:
    """Switch the underlying arm controller mode if needed.

    Gravity-comp mode uses MIT (with kp/kd from config); POSITION mode
    uses POS_VEL. ``arm.mode_*`` is idempotent and safe to call when
    already in the target mode, but skipping the call when possible
    avoids the per-call ``stabilize_delay`` (~200 ms).
    """
    if target_mode == MODE_GRAVITY_COMP and arm.mode != "mit":
        arm.mode_mit(
            kp=np.asarray(gravity_kp, dtype=float),
            kd=np.asarray(gravity_kd, dtype=float),
        )
    elif target_mode == MODE_POSITION and arm.mode != "pos_vel":
        arm.mode_pos_vel()


def run_server(cfg: DaemonConfig) -> None:
    arm = RobotArm(cfg.arm_config)
    arm.connect()
    arm.enable()
    n = arm.num_joints

    safety = SafetyManager(cfg.safety, dof=n)
    state = SharedRobotState(dof=n)
    ee = EEPose()

    grav = GravityCompLockController(cfg.gravity_comp, n)
    posctl = PositionController(n)

    # Start in gravity-comp mode (matches the backend default and lets
    # the operator move the arm before the first command).
    _switch_arm_mode(
        arm, MODE_GRAVITY_COMP, cfg.gravity_comp.kp, cfg.gravity_comp.kd
    )
    mode = {"current": MODE_GRAVITY_COMP}

    last_q = arm.get_positions(request=True).astype(float)
    last_t = time.monotonic()

    def control_callback(arm: RobotArm, dt: float) -> None:
        nonlocal last_q, last_t

        q = arm.get_positions()

        # Crude EE velocity via finite difference between successive
        # control ticks. Refine with the analytic Jacobian (example 10)
        # if the noise floor proves problematic in practice.
        now = time.monotonic()
        dt2 = max(now - last_t, 1e-3)
        ee_pos, ee_rotvec = ee.pose(q)
        ee_pos_prev, _ = ee.pose(last_q)
        ee_lin_vel = (ee_pos - ee_pos_prev) / dt2
        ee_ang_vel = np.zeros(3, dtype=np.float32)

        # Motor temperatures aren't exposed by the current SDK; fall
        # back to zeros so the safety manager's thermal watchdog
        # degrades gracefully instead of false-tripping.
        try:
            temps = np.asarray(arm.get_temperatures(), dtype=np.float32)
        except AttributeError:
            temps = np.zeros(n, dtype=np.float32)

        try:
            taus = np.asarray(arm.get_torques(), dtype=np.float32)
        except AttributeError:
            taus = np.zeros(n, dtype=np.float32)

        try:
            qd = np.asarray(arm.get_velocities(), dtype=np.float32)
        except AttributeError:
            qd = np.zeros(n, dtype=np.float32)

        state.set(
            joint_pos=q.astype(np.float32),
            joint_vel=qd,
            joint_effort=taus,
            ee_pos=ee_pos,
            ee_rotvec=ee_rotvec,
            gripper_pos=None,
            motor_temps_c=temps,
            motor_torques_nm=taus,
        )

        # Safety state machine — freeze (gravity-only, zero ee velocity
        # so the lock target doesn't drift) on any active fault or
        # heartbeat timeout.
        safety.evaluate_thermal(temps)
        if safety.is_active_fault() or safety.heartbeat_state() != SAFETY_OK:
            grav.step(arm, np.zeros(3), np.zeros(3))
        elif mode["current"] == MODE_GRAVITY_COMP:
            grav.step(arm, ee_lin_vel, ee_ang_vel)
        else:
            posctl.step(arm)

        last_q = q.copy()
        last_t = now

    arm.start_control_loop(control_callback, rate=cfg.control_rate_hz)

    ctx = zmq.Context()
    sock = ctx.socket(zmq.REP)
    sock.bind(cfg.zmq_address)
    sock.setsockopt(zmq.RCVTIMEO, 100)

    print(f"[rebotarm-daemon] listening on {cfg.zmq_address}")
    stopped = False
    try:
        while not stopped:
            try:
                msg = sock.recv_json()
            except zmq.Again:
                continue
            except (ValueError, zmq.ZMQError) as e:
                # REP state machine requires a reply before the next
                # recv, otherwise the socket desyncs.
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
                sock.send_json({
                    "ok": True,
                    "dof": n,
                    "joint_names": list(arm.joint_names),
                    "ee_frame": ee.ee_frame_name,
                })
            elif cmd == CMD_HEARTBEAT:
                safety.note_heartbeat()
                sock.send_json({"ok": True})
            elif cmd == CMD_READ_STATE:
                snap = state.snapshot()
                payload = {
                    "joint_pos": snap["joint_pos"].tolist(),
                    "joint_vel": snap["joint_vel"].tolist(),
                    "joint_effort": snap["joint_effort"].tolist(),
                    "ee_pos": None if snap["ee_pos"] is None else snap["ee_pos"].tolist(),
                    "ee_rotvec": None if snap["ee_rotvec"] is None else snap["ee_rotvec"].tolist(),
                    "gripper_pos": snap["gripper_pos"],
                    "safety_state": safety.overall_state(snap["motor_temps_c"]),
                    "t_mono_ns": time.monotonic_ns(),
                }
                sock.send_json(payload)
            elif cmd == CMD_SEND_COMMAND:
                if safety.is_active_fault() or safety.heartbeat_state() != SAFETY_OK:
                    sock.send_json({"ok": False, "error": "safety fault active"})
                else:
                    q_req = np.asarray(msg.get("q", [0.0] * n), dtype=float)
                    q_req = safety.clamp_joint_pos(q_req)
                    posctl.set_target(q_req)
                    sock.send_json({"ok": True})
            elif cmd == CMD_SET_MODE:
                m = msg.get("mode", MODE_GRAVITY_COMP)
                if m not in (MODE_POSITION, MODE_GRAVITY_COMP):
                    sock.send_json({"ok": False, "error": f"unknown mode: {m}"})
                else:
                    try:
                        _switch_arm_mode(
                            arm, m, cfg.gravity_comp.kp, cfg.gravity_comp.kd
                        )
                        # Reset the controller's held target so it
                        # re-anchors at the current pose on the next tick.
                        if m == MODE_POSITION:
                            posctl.reset()
                        else:
                            grav.reset()
                        mode["current"] = m
                        sock.send_json({"ok": True, "mode": m})
                    except Exception as exc:  # noqa: BLE001 — surface to client
                        sock.send_json({"ok": False, "error": f"mode switch failed: {exc}"})
            elif cmd == CMD_ESTOP:
                safety.trigger_estop()
                try:
                    arm.disable()
                except Exception:
                    pass
                sock.send_json({"ok": True})
            elif cmd == CMD_CLEAR_ESTOP:
                snap = state.snapshot()
                if safety.try_clear_estop(snap["motor_temps_c"]):
                    try:
                        arm.enable()
                    except Exception:
                        pass
                    sock.send_json({"ok": True})
                else:
                    sock.send_json({"ok": False, "reason": "preconditions not met"})
            elif cmd == CMD_GET_SAFETY_STATUS:
                snap = state.snapshot()
                sock.send_json({
                    "safety_state": safety.overall_state(snap["motor_temps_c"]),
                    "mode": mode["current"],
                })
            elif cmd == CMD_DISCONNECT:
                stopped = True
                sock.send_json({"ok": True})
            else:
                sock.send_json({"ok": False, "error": f"unknown cmd: {cmd}"})
    finally:
        try:
            arm.disconnect()
        except Exception:
            pass
        sock.close(linger=0)
        ctx.term()
