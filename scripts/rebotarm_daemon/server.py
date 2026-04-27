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
from typing import Optional  # noqa: F401  (used by Gripper annotation below)

import numpy as np
import zmq

from reBotArm_control_py.actuator import Gripper, RobotArm

from rebotarm_daemon.config import DaemonConfig
from rebotarm_daemon.controllers import (
    GravityCompController,
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


def _ramp_disable(arm: RobotArm, n: int, secs: float = 1.0, rate_hz: int = 100) -> None:
    """Ramp ``kp`` -> 0 over ``secs`` seconds while keeping ``tau_g`` active.

    A QDD arm has no mechanical brakes — calling ``arm.disable()`` while the
    arm is held against gravity makes it drop. This helper softens the
    landing by ramping kp to zero (so the position-error term goes away)
    while still feeding the gravity-comp torque, then returns. The caller
    is expected to invoke ``arm.disable()``/``arm.disconnect()`` after.

    Race note: ``arm.start_control_loop`` runs its callback on a daemon
    thread (verified in actuator/arm.py). The reBotArm SDK does not expose
    a ``stop_control_loop`` API, so the callback may continue issuing its
    own ``arm.mit(...)`` calls in parallel with this ramp. The SDK's
    per-call ``try/except CallError`` papers over conflicts; the ramp will
    still mostly converge. If the SDK adds a stop API, gate that here.
    """
    import time as _time  # local import — keep top-of-file lean
    from reBotArm_control_py.dynamics import compute_generalized_gravity
    steps = max(1, int(secs * rate_hz))
    try:
        q_hold = arm.get_positions().copy()
    except Exception:
        return
    for i in range(steps + 1):
        kp_scale = 1.0 - (i / steps)
        kp = np.full(n, 2.0 * kp_scale)
        kd = np.full(n, 1.0)
        try:
            tau_g = compute_generalized_gravity(q=arm.get_positions())
            arm.mit(
                pos=q_hold,
                vel=np.zeros(n),
                kp=kp,
                kd=kd,
                tau=tau_g,
                request_feedback=True,
            )
        except Exception:
            return
        _time.sleep(1.0 / rate_hz)


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

    grav = GravityCompController(cfg.gravity_comp, n, safety=safety)
    posctl = PositionController(n)

    # Optional gripper sharing the arm's CAN/serial bus. When configured,
    # we inject the arm's Controller into the Gripper so both sides talk
    # over the same bus instead of fighting for /dev/ttyACM0. The Gripper
    # runs its own 100 Hz compliance loop (kp=0 + velocity-direction
    # friction comp) that mirrors data_collect/11_gravity_compensation_record.py.
    gripper: Optional[Gripper] = None
    if cfg.gripper is not None:
        shared_ctrl = next(iter(arm._ctrl_map.values()))
        gripper = Gripper(cfg_path=cfg.gripper.cfg_path, controller=shared_ctrl)
        gripper.enable()
        gripper.mode_mit(kp=0.0, kd=cfg.gripper.kd)
        gripper_params = cfg.gripper

        def _gripper_compliance(g: Gripper, _dt: float) -> None:
            pos, vel, _ = g.get_state(request=False)
            if abs(vel) > gripper_params.vel_deadband_rad_s:
                tau = gripper_params.friction_tau_nm * (1.0 if vel > 0 else -1.0)
            else:
                tau = 0.0
            g.mit(pos=pos, vel=0.0, kp=0.0, kd=gripper_params.kd, tau=tau)

        gripper.start_control_loop(
            _gripper_compliance, rate=float(gripper_params.control_rate_hz)
        )

    # Force the underlying motors into MIT mode at startup. RobotArm's
    # __init__ sets self._mode = "mit" as a Python-side default, but the
    # motor hardware may have been left in POS_VEL by a previous process
    # (its mode persists across power-cycles). Without this explicit call,
    # _switch_arm_mode below sees ``arm.mode == "mit"`` and skips
    # mode_mit() — so motors stay in their residual mode and the kp/kd we
    # send via arm.mit() get reinterpreted incorrectly. This was the
    # cause of joints 1-3 (4340P) appearing locked in gravity-comp mode.
    arm.mode_mit(
        kp=np.asarray(cfg.gravity_comp.kp, dtype=float),
        kd=np.asarray(cfg.gravity_comp.kd, dtype=float),
    )
    mode = {"current": MODE_GRAVITY_COMP}

    def control_callback(arm: RobotArm, dt: float) -> None:
        q = arm.get_positions()
        ee_pos, ee_rotvec = ee.pose(q)

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

        gripper_pos = None
        if gripper is not None:
            try:
                gripper_pos = float(gripper.get_position(request=False))
            except Exception:
                gripper_pos = None

        state.set(
            joint_pos=q.astype(np.float32),
            joint_vel=qd,
            joint_effort=taus,
            ee_pos=ee_pos,
            ee_rotvec=ee_rotvec,
            gripper_pos=gripper_pos,
            motor_temps_c=temps,
            motor_torques_nm=taus,
        )

        # Safety state machine — fall back to pure gravity comp on any
        # active fault or heartbeat timeout, regardless of the requested
        # mode.
        safety.evaluate_thermal(temps)
        if (
            safety.is_active_fault()
            or safety.heartbeat_state() != SAFETY_OK
            or mode["current"] == MODE_GRAVITY_COMP
        ):
            grav.step(arm)
        else:
            posctl.step(arm)

    arm.start_control_loop(control_callback, rate=cfg.control_rate_hz)

    ctx = zmq.Context()
    sock = ctx.socket(zmq.REP)
    sock.bind(cfg.zmq_address)
    sock.setsockopt(zmq.RCVTIMEO, 100)

    print(f"[rebotarm-daemon] listening on {cfg.zmq_address}")
    # Daemon survives client connect/disconnect cycles. The hardware loop
    # runs once per process; clients (the backend) come and go via ZMQ.
    # Process exits only on SIGINT/SIGTERM (KeyboardInterrupt) below.
    try:
        while True:
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
                elif mode["current"] != MODE_POSITION:
                    # The control callback only feeds posctl.set_target() into
                    # the arm when mode == POSITION; in gravity-comp mode the
                    # request would silently no-op. Reject so callers (e.g.
                    # the replay path) hit a loud error instead of a ghost.
                    sock.send_json({
                        "ok": False,
                        "error": "send_command requires position mode",
                    })
                else:
                    snap = state.snapshot()
                    q_req = np.asarray(msg.get("q", [0.0] * n), dtype=float)
                    # Multi-layer safety: clamp pos -> ramp velocity -> ramp
                    # accel. Velocity is enforced against the most recent
                    # measured q (one tick behind the control loop, ~2 ms at
                    # 500 Hz). The accel ramp keeps its own internal
                    # `_last_q`, so it bounds command jerk vs. its own
                    # previous output.
                    dt = 1.0 / cfg.control_rate_hz
                    q_req = safety.clamp_joint_pos(q_req)
                    q_req = safety.ramp_velocity(snap["joint_pos"], q_req, dt)
                    q_req = safety.ramp_accel(q_req, dt)
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
                # Soft disconnect — acknowledge but keep running. Reset to
                # gravity_comp so the next client connects to a known-safe
                # compliant state instead of inheriting whatever mode the
                # previous client left behind (e.g., POSITION holding pose
                # after a replay).
                try:
                    _switch_arm_mode(
                        arm, MODE_GRAVITY_COMP,
                        cfg.gravity_comp.kp, cfg.gravity_comp.kd,
                    )
                    mode["current"] = MODE_GRAVITY_COMP
                    grav.reset()
                    posctl.reset()
                except Exception:
                    pass
                sock.send_json({"ok": True})
            else:
                sock.send_json({"ok": False, "error": f"unknown cmd: {cmd}"})
    finally:
        # Soft-stop: ramp kp to zero while holding tau_g so the QDD arm
        # doesn't drop when we cut torque. The SDK's start_control_loop
        # thread is still running here (no SDK stop API), but the per-call
        # CallError handling papers over the resulting parallel mit() calls.
        try:
            _ramp_disable(arm, n)
        except Exception:
            pass
        # Stop gripper compliance loop and disable BEFORE arm.disconnect():
        # the gripper shares the arm's Controller, so once arm.disconnect()
        # closes the bus, gripper commands would call into a dead handle.
        if gripper is not None:
            try:
                gripper.stop_control_loop()
            except Exception:
                pass
            try:
                gripper.disable()
            except Exception:
                pass
            try:
                gripper.disconnect()
            except Exception:
                pass
        try:
            arm.disconnect()
        except Exception:
            pass
        sock.close(linger=0)
        ctx.term()
