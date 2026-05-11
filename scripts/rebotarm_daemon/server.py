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

Reconnect model
---------------
``run_server`` runs an outer retry loop. ``_connect_arm_with_retry``
keeps trying to construct + enable a ``RobotArm`` instance every
``cfg.reconnect_interval_s`` until it succeeds — ZMQ is NOT bound while
this is happening, so callers see ``connection refused`` until the
daemon is ready. After connect succeeds, ``_serve_one_session`` does
the per-session work (controllers, gripper, ZMQ, message loop) inside
its own try/finally. If the control callback sees a sustained run of
SDK exceptions (``cfg.disconnect_fault_threshold`` consecutive faults)
it sets a disconnect event, the message loop raises
``_ArmDisconnected``, teardown runs, and the outer loop reconnects.

Wire-protocol constants are duplicated from
``backend/mimicrec/adapters/rebotarm_protocol.py`` because the daemon
runs in a separate venv and cannot import the backend package. Keep
them in sync.
"""
from __future__ import annotations

import threading
import time
from typing import Optional  # noqa: F401  (used by Gripper annotation below)

import numpy as np
import zmq

from reBotArm_control_py.actuator import Gripper, RobotArm
from reBotArm_control_py.dynamics import load_dynamics_model, set_gravity

from rebotarm_daemon.config import DaemonConfig, clamp_gripper_target
from rebotarm_daemon.controllers import (
    GravityCompController,
    PositionController,
)
from rebotarm_daemon.ee_pose import EEPose
from rebotarm_daemon.enable_switch import make_enable_switch
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
CMD_SEND_GRIPPER_COMMAND = "send_gripper_command"
CMD_SET_MODE = "set_mode"
CMD_HEARTBEAT = "heartbeat"
CMD_ESTOP = "estop"
CMD_CLEAR_ESTOP = "clear_estop"
CMD_GET_SAFETY_STATUS = "get_safety_status"

MODE_POSITION = "position"
MODE_GRAVITY_COMP = "gravity_comp"

SAFETY_OK = "ok"


class _ArmDisconnected(Exception):
    """Signal raised from the message loop when the control callback
    observed enough consecutive SDK exceptions to conclude the hardware
    has gone away. The outer retry loop in ``run_server`` catches this
    and reconnects after ``cfg.reconnect_interval_s``.
    """


def _ramp_disable(arm: RobotArm, n: int, secs: float = 1.0, rate_hz: int = 100) -> None:
    """Ramp ``kp`` -> 0 over ``secs`` seconds while keeping ``tau_g`` active.

    A QDD arm has no mechanical brakes — calling ``arm.disable()`` while the
    arm is held against gravity makes it drop. This helper softens the
    landing by ramping kp to zero (so the position-error term goes away)
    while still feeding the gravity-comp torque, then returns. The caller
    is expected to invoke ``arm.disable()``/``arm.disconnect()`` after.

    Called only AFTER ``arm.stop_control_loop()`` returns, so the SDK's
    control thread has joined and there's no parallel ``arm.mit(...)``
    racing us here.
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


# NOTE: ``_switch_arm_mode`` was removed in favour of staying in MIT
# throughout the daemon's lifetime. POSITION and GRAVITY_COMP are now
# pure software dispatch — the only thing the motor sees is different
# kp/kd/pos/tau values per tick. mode_pos_vel() used to drop the QDD
# arm under gravity during the ~200 ms stabilize per motor; this design
# eliminates that failure mode entirely.


def _connect_arm_with_retry(cfg: DaemonConfig) -> RobotArm:
    """Construct + enable a ``RobotArm`` instance, retrying on any failure.

    Returns only when the arm is up. On each failure the partially-built
    arm (if any) is best-effort torn down and we sleep
    ``cfg.reconnect_interval_s`` before the next attempt.

    Re-constructs the ``RobotArm`` on every attempt rather than calling
    ``arm.reconnect()``. The SDK's ``reconnect()`` iterates the
    ``_ctrl_map`` to rebuild controllers, but ``disconnect()`` clears
    that map first — so a reconnect call after a disconnect rebuilds
    zero controllers and the next ``enable()`` ``KeyError``s. Building
    a fresh ``RobotArm`` runs ``_setup_motors`` end-to-end, which is
    correct in all cases.
    """
    retry_s = max(0.1, float(cfg.reconnect_interval_s))
    attempt = 0
    while True:
        attempt += 1
        arm: Optional[RobotArm] = None
        try:
            arm = RobotArm(cfg.arm_config)
            arm.enable()
            print(
                f"[rebotarm-daemon] arm connected (attempt {attempt})",
                flush=True,
            )
            return arm
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(
                f"[rebotarm-daemon] arm connect failed (attempt {attempt}): "
                f"{type(e).__name__}: {e}; retrying in {retry_s:.1f}s",
                flush=True,
            )
            # Best-effort cleanup of whatever partial state ``RobotArm``
            # /``enable`` got to before failing. The serial port may be
            # half-open; ``disconnect()`` releases it so the next attempt
            # can re-open without an "device busy" race.
            if arm is not None:
                try:
                    arm.stop_control_loop()
                except Exception:
                    pass
                try:
                    arm.disconnect()
                except Exception:
                    pass
            time.sleep(retry_s)


def run_server(cfg: DaemonConfig) -> None:
    # Apply the configured mount-aware gravity vector to the cached
    # dynamics model BEFORE any controller is constructed.
    # controllers.py (GravityCompController.compute,
    # PositionController.compute) and _ramp_disable in this file all
    # call compute_generalized_gravity() without an explicit model, so
    # they hit this cached instance. Setting it here once means the
    # downstream controllers see the right gravity from the first tick.
    model = load_dynamics_model()
    set_gravity(model, tuple(cfg.gravity_in_base))
    print(
        f"[rebotarm-daemon] gravity_in_base = {cfg.gravity_in_base}",
        flush=True,
    )

    # Optional hardware enable-switch (deadman). Hoisted OUT of the
    # session because the GPIO line is independent of the arm — its
    # physical state should persist across an arm reconnect cycle. When
    # active, the daemon holds the current pose and rejects motion
    # commands. ``None`` means either the YAML section was omitted or
    # GPIO init failed; the daemon then behaves as if the line is
    # permanently unlocked.
    enable_switch = make_enable_switch(cfg.enable_switch)
    if enable_switch is not None:
        print("[rebotarm-daemon] enable_switch armed", flush=True)

    retry_s = max(0.1, float(cfg.reconnect_interval_s))

    try:
        while True:
            try:
                _serve_one_session(cfg, enable_switch)
            except KeyboardInterrupt:
                raise
            except _ArmDisconnected as e:
                print(
                    f"[rebotarm-daemon] arm disconnected ({e}); "
                    f"reconnecting in {retry_s:.1f}s",
                    flush=True,
                )
                time.sleep(retry_s)
            except Exception as e:
                # An unexpected exception from the session shouldn't bring
                # down the daemon — log it and retry. KeyboardInterrupt is
                # already handled above so it still terminates cleanly.
                print(
                    f"[rebotarm-daemon] session ended unexpectedly "
                    f"({type(e).__name__}: {e}); reconnecting in {retry_s:.1f}s",
                    flush=True,
                )
                time.sleep(retry_s)
    except KeyboardInterrupt:
        print("[rebotarm-daemon] interrupted; exiting", flush=True)
    finally:
        if enable_switch is not None:
            try:
                enable_switch.close()
            except Exception:
                pass


def _serve_one_session(cfg: DaemonConfig, enable_switch) -> None:
    """One connect → run → teardown cycle.

    Returns normally only on ``KeyboardInterrupt``. Raises
    ``_ArmDisconnected`` (or any other unexpected exception) to signal
    the outer retry loop to reconnect.
    """
    arm = _connect_arm_with_retry(cfg)
    n = arm.num_joints

    safety = SafetyManager(cfg.safety, dof=n)
    state = SharedRobotState(dof=n)
    ee = EEPose()

    grav = GravityCompController(cfg.gravity_comp, n, safety=safety)
    posctl = PositionController(cfg.position, n, safety=safety)

    # Define ``mode`` BEFORE the gripper control loop is spawned — the
    # gripper callback closes over it and the loop thread starts firing
    # ticks immediately on start_control_loop, so a NameError lookup is
    # possible if mode isn't bound yet. Initial value is set here and
    # overwritten unconditionally in the arm.mode_mit block below.
    mode = {"current": MODE_GRAVITY_COMP}

    # Optional gripper sharing the arm's CAN/serial bus. When configured,
    # we inject the arm's Controller into the Gripper so both sides talk
    # over the same bus instead of fighting for /dev/ttyACM0. The 100 Hz
    # gripper loop dispatches by daemon mode:
    #   - GRAVITY_COMP → compliance loop (kp=0 + velocity-direction
    #     friction comp), mirroring data_collect/11_gravity_compensation_record.py
    #   - POSITION    → MIT position-tracking with cfg.gripper.position_kp/kd,
    #     following the latest target set via CMD_SEND_GRIPPER_COMMAND
    gripper: Optional[Gripper] = None
    # ``gripper_target[0] = float | None``. Mutable cell so the message
    # loop can rebind without ``nonlocal`` gymnastics in the closure.
    gripper_target: list = [None]
    sock: Optional[zmq.Socket] = None
    ctx: Optional[zmq.Context] = None
    try:
        if cfg.gripper is not None:
            shared_ctrl = next(iter(arm._ctrl_map.values()))
            gripper = Gripper(cfg_path=cfg.gripper.cfg_path, controller=shared_ctrl)
            gripper.enable()
            gripper.mode_mit(kp=0.0, kd=cfg.gripper.kd)
            gripper_params = cfg.gripper

            def _gripper_callback(g: Gripper, _dt: float) -> None:
                if (
                    mode["current"] == MODE_POSITION
                    and gripper_target[0] is not None
                ):
                    # Position-tracking: follow the replay/teleop target.
                    g.mit(
                        pos=float(gripper_target[0]),
                        vel=0.0,
                        kp=float(gripper_params.position_kp),
                        kd=float(gripper_params.position_kd),
                        tau=0.0,
                    )
                    return
                # Compliance fallback (GRAVITY_COMP, or POSITION before any
                # target has arrived — stay free instead of locking at zero).
                pos, vel, _ = g.get_state(request=False)
                if abs(vel) > gripper_params.vel_deadband_rad_s:
                    tau = gripper_params.friction_tau_nm * (1.0 if vel > 0 else -1.0)
                else:
                    tau = 0.0
                # Constant open-direction bias so the gripper drifts toward
                # open when not actively held. Added on top of friction comp.
                tau += gripper_params.open_bias_tau_nm
                g.mit(pos=pos, vel=0.0, kp=0.0, kd=gripper_params.kd, tau=tau)

            gripper.start_control_loop(
                _gripper_callback, rate=float(gripper_params.control_rate_hz)
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
        mode["current"] = MODE_GRAVITY_COMP
        # Wall-clock timestamp of the last CMD_SEND_COMMAND we accepted, used
        # to compute the real elapsed dt for safety.ramp_velocity/ramp_accel.
        # Replay sends commands at the trajectory's native rate (~28-30 Hz),
        # not at the daemon's 500 Hz tick — using control_rate_hz here would
        # over-clamp by ~17x, leaving the arm lagging the command until the
        # watchdog trips on joint_position_jump.
        last_cmd_t: list = [None]  # mutable cell so the message loop can rebind
        # Edge tracker for the unified lock state (GPIO switch OR latched
        # ESTOP). Rising edge snapshots the current pose into posctl so the
        # arm holds where it was; falling edge drops to GRAVITY_COMP and
        # waits for an explicit set_mode from the client (no auto-resume).
        was_locked: list = [False]

        def _is_locked_now() -> bool:
            gpio_locked = enable_switch.is_locked() if enable_switch else False
            return gpio_locked or safety._estop_active

        # Disconnect detection: the control callback increments
        # ``consecutive_faults`` whenever its body raises and resets to
        # zero on each successful tick. Once we cross the threshold the
        # event is set; the message loop raises ``_ArmDisconnected`` on
        # the next 100 ms recv timeout. Threshold defaults to 250 ticks
        # ≈ 500 ms at 500 Hz — bursts of 10-30 ``CallError`` during a
        # damiao CAN brown-out are normal and self-recover well below
        # this floor.
        disconnect_event = threading.Event()
        consecutive_faults = [0]
        fault_threshold = max(1, int(cfg.disconnect_fault_threshold))

        def control_callback(arm: RobotArm, dt: float) -> None:
            try:
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

                # Safety state machine. Three precedence levels, top to bottom:
                #   1. Thermal / torque fault / heartbeat timeout → gravity comp.
                #      A hot motor or a stuck client should drop torque, not
                #      hold pose with strong kp (which keeps drawing current).
                #   2. Lock active (GPIO switch or latched ESTOP) → hold the
                #      snapshot pose with posctl. ESTOP no longer calls
                #      arm.disable(); the QDD arm has no brakes so killing
                #      torque would drop it. Holding pose under MIT control is
                #      the safer Cat-2 behaviour.
                #   3. Otherwise honour the requested mode.
                safety.evaluate_thermal(temps)
                locked_now = _is_locked_now()
                if locked_now and not was_locked[0]:
                    # Rising edge: anchor posctl at the current pose and force
                    # POSITION dispatch. The gripper, if present, also gets
                    # snapshotted so it holds in place under its position
                    # callback instead of going compliant.
                    posctl.set_target(q.copy())
                    safety.reset_ramp_state()
                    last_cmd_t[0] = None
                    if gripper is not None and gripper_pos is not None:
                        gripper_target[0] = gripper_pos
                    else:
                        gripper_target[0] = None
                    mode["current"] = MODE_POSITION
                elif not locked_now and was_locked[0]:
                    # Falling edge: client must explicitly re-enter POSITION;
                    # default to compliance so the arm doesn't suddenly track
                    # a stale target.
                    grav.reset()
                    posctl.reset()
                    safety.reset_ramp_state()
                    last_cmd_t[0] = None
                    gripper_target[0] = None
                    mode["current"] = MODE_GRAVITY_COMP
                was_locked[0] = locked_now

                non_estop_fault = safety._thermal_active or safety._torque_active
                if non_estop_fault or safety.heartbeat_state() != SAFETY_OK:
                    grav.step(arm)
                elif locked_now:
                    posctl.step(arm)
                elif mode["current"] == MODE_GRAVITY_COMP:
                    grav.step(arm)
                else:
                    posctl.step(arm)
                consecutive_faults[0] = 0
            except Exception:
                # MUST catch every exception. The SDK's
                # ``_control_loop_impl`` re-raises if our callback throws
                # while ``_running`` is True, which kills the SDK thread
                # and we'd silently stop running. Counting faults here
                # lets the message loop notice the hardware is gone and
                # trigger a clean reconnect cycle instead.
                consecutive_faults[0] += 1
                if consecutive_faults[0] >= fault_threshold:
                    disconnect_event.set()

        arm.start_control_loop(control_callback, rate=cfg.control_rate_hz)

        ctx = zmq.Context()
        sock = ctx.socket(zmq.REP)
        sock.bind(cfg.zmq_address)
        sock.setsockopt(zmq.RCVTIMEO, 100)

        print(f"[rebotarm-daemon] listening on {cfg.zmq_address}", flush=True)
        # Daemon survives client connect/disconnect cycles. The hardware loop
        # runs once per session; clients (the backend) come and go via ZMQ.
        # Process exits only on SIGINT/SIGTERM (KeyboardInterrupt) below;
        # arm disconnect raises ``_ArmDisconnected`` which the outer
        # ``run_server`` loop catches to reconnect.
        while True:
            if disconnect_event.is_set():
                raise _ArmDisconnected(
                    f"{fault_threshold}+ consecutive SDK exceptions in control loop"
                )
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
                gpio_locked = (
                    bool(enable_switch.is_locked()) if enable_switch else False
                )
                payload = {
                    "joint_pos": snap["joint_pos"].tolist(),
                    "joint_vel": snap["joint_vel"].tolist(),
                    "joint_effort": snap["joint_effort"].tolist(),
                    "ee_pos": None if snap["ee_pos"] is None else snap["ee_pos"].tolist(),
                    "ee_rotvec": None if snap["ee_rotvec"] is None else snap["ee_rotvec"].tolist(),
                    "gripper_pos": snap["gripper_pos"],
                    "safety_state": safety.overall_state(snap["motor_temps_c"]),
                    # Unified lock state, ORed across the GPIO deadman
                    # switch and the latched ESTOP. UI can show a single
                    # "locked" badge; clients that need finer detail can
                    # split on enable_switch_locked vs the safety_state
                    # "estop" value.
                    "locked": gpio_locked or safety._estop_active,
                    "enable_switch_locked": gpio_locked,
                    "t_mono_ns": time.monotonic_ns(),
                }
                sock.send_json(payload)
            elif cmd == CMD_SEND_COMMAND:
                if _is_locked_now():
                    sock.send_json({
                        "ok": False,
                        "error": "enable switch / estop locked",
                    })
                elif safety.is_active_fault() or safety.heartbeat_state() != SAFETY_OK:
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
                    # accel. Use the real elapsed wall time since the last
                    # accepted command so the velocity/accel limits express
                    # genuine rad/s and rad/s² regardless of how often the
                    # client sends. Cap at 100 ms to avoid letting a long
                    # gap (e.g., session reconnect) authorize a giant step.
                    now_t = time.monotonic()
                    if last_cmd_t[0] is None:
                        dt = 1.0 / cfg.control_rate_hz
                    else:
                        dt = min(max(now_t - last_cmd_t[0], 1e-3), 0.1)
                    last_cmd_t[0] = now_t
                    q_req = safety.clamp_joint_pos(q_req)
                    q_req = safety.ramp_velocity(snap["joint_pos"], q_req, dt)
                    q_req = safety.ramp_accel(q_req, dt)
                    posctl.set_target(q_req)
                    sock.send_json({"ok": True})
            elif cmd == CMD_SET_MODE:
                m = msg.get("mode", MODE_GRAVITY_COMP)
                if _is_locked_now():
                    sock.send_json({
                        "ok": False,
                        "error": "enable switch / estop locked",
                    })
                elif m not in (MODE_POSITION, MODE_GRAVITY_COMP):
                    sock.send_json({"ok": False, "error": f"unknown mode: {m}"})
                else:
                    # Pure software-mode swap. Motors stay in MIT; the
                    # control_callback dispatch picks grav.step (kp=0) or
                    # posctl.step (kp=high) per tick. Reset the inactive
                    # controller's target so it re-anchors at the current
                    # pose when it next runs. Also clear ramp state /
                    # last-command timestamp so the first command after
                    # entering POSITION uses a fresh baseline.
                    if m == MODE_POSITION:
                        posctl.reset()
                        safety.reset_ramp_state()
                        last_cmd_t[0] = None
                    else:
                        grav.reset()
                        # Drop the gripper position target so the gripper
                        # falls back to compliance once we leave POSITION.
                        gripper_target[0] = None
                    mode["current"] = m
                    sock.send_json({"ok": True, "mode": m})
            elif cmd == CMD_SEND_GRIPPER_COMMAND:
                if _is_locked_now():
                    sock.send_json({
                        "ok": False,
                        "error": "enable switch / estop locked",
                    })
                elif gripper is None:
                    sock.send_json({
                        "ok": False,
                        "error": "no gripper configured on this daemon",
                    })
                elif mode["current"] != MODE_POSITION:
                    sock.send_json({
                        "ok": False,
                        "error": "send_gripper_command requires position mode",
                    })
                else:
                    try:
                        raw = float(msg["gripper"])
                    except (KeyError, TypeError, ValueError) as exc:
                        sock.send_json({
                            "ok": False,
                            "error": f"bad gripper payload: {exc}",
                        })
                    else:
                        clamped = clamp_gripper_target(raw, gripper_params)
                        if clamped != raw:
                            lo = gripper_params.position_min_rad
                            hi = gripper_params.position_max_rad
                            lo_s = "-inf" if lo is None else f"{lo:.4f}"
                            hi_s = "+inf" if hi is None else f"{hi:.4f}"
                            print(
                                f"[rebotarm-daemon] gripper clamp "
                                f"{raw:.4f} -> {clamped:.4f} "
                                f"(range [{lo_s}, {hi_s}])"
                            )
                        gripper_target[0] = clamped
                        sock.send_json({"ok": True, "clamped": clamped != raw})
            elif cmd == CMD_ESTOP:
                # Unified lock: latch the estop flag so the control loop
                # snapshots the current pose and holds it. We deliberately
                # do NOT call arm.disable() — the QDD arm has no brakes and
                # cutting torque would drop it. Posctl holding pose under
                # MIT is the safer Cat-2 behaviour, and matches the
                # hardware enable-switch path so the front-end E-stop
                # button and the deadman switch produce identical state.
                safety.trigger_estop()
                sock.send_json({"ok": True})
            elif cmd == CMD_CLEAR_ESTOP:
                snap = state.snapshot()
                if safety.try_clear_estop(snap["motor_temps_c"]):
                    # No arm.enable() here: the arm was never disabled by
                    # CMD_ESTOP under the unified-lock semantics, so it
                    # remains enabled throughout. If the GPIO switch is
                    # still asserted the daemon stays locked; on the next
                    # control tick the falling edge fires once both
                    # sources are clear.
                    sock.send_json({"ok": True})
                else:
                    sock.send_json({"ok": False, "reason": "preconditions not met"})
            elif cmd == CMD_GET_SAFETY_STATUS:
                snap = state.snapshot()
                gpio_locked = (
                    bool(enable_switch.is_locked()) if enable_switch else False
                )
                sock.send_json({
                    "safety_state": safety.overall_state(snap["motor_temps_c"]),
                    "mode": mode["current"],
                    "locked": gpio_locked or safety._estop_active,
                    "enable_switch_locked": gpio_locked,
                })
            elif cmd == CMD_DISCONNECT:
                # Soft disconnect — acknowledge but keep running. Reset to
                # gravity_comp so the next client connects to a known-safe
                # compliant state instead of inheriting whatever mode the
                # previous client left behind (e.g., POSITION holding pose
                # after a replay).
                mode["current"] = MODE_GRAVITY_COMP
                grav.reset()
                posctl.reset()
                safety.reset_ramp_state()
                last_cmd_t[0] = None
                gripper_target[0] = None
                sock.send_json({"ok": True})
            else:
                sock.send_json({"ok": False, "error": f"unknown cmd: {cmd}"})
    finally:
        # Teardown order matters:
        #   1. Stop the arm control loop FIRST so the SDK thread joins
        #      and stops calling ``arm.mit()`` mid-teardown.
        #   2. Soft-stop (ramp kp → 0 while holding tau_g) so the QDD
        #      arm doesn't drop. Safe to run with the SDK thread joined
        #      — no parallel ``mit()`` calls fight with us.
        #   3. Stop + disable + disconnect the gripper. Gripper shares
        #      the arm's Controller, so it must release before the arm
        #      tears the bus down.
        #   4. ``arm.disconnect()`` releases the serial port.
        #   5. ZMQ teardown last — once we close ``ctx`` we can't reply
        #      anyway, and pending replies are dropped via ``linger=0``.
        # Every step is best-effort: on a real disconnect any of these
        # may raise OSError / serial errors. We swallow and continue so
        # the outer retry loop gets a clean handoff.
        try:
            arm.stop_control_loop()
        except Exception:
            pass
        try:
            _ramp_disable(arm, n)
        except Exception:
            pass
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
        if sock is not None:
            try:
                sock.close(linger=0)
            except Exception:
                pass
        if ctx is not None:
            try:
                ctx.term()
            except Exception:
                pass
