"""Testable protocol and safety state machine for the SO-101 daemon."""
from __future__ import annotations

import threading
import time

import numpy as np

from so101_daemon.config import SO101DaemonConfig
from so101_daemon.hardware import ALL_JOINT_NAMES, ARM_JOINT_NAMES


CMD_CONNECT = "connect"
CMD_DISCONNECT = "disconnect"
CMD_READ_STATE = "read_state"
CMD_SEND_COMMAND = "send_command"
CMD_SEND_GRIPPER_COMMAND = "send_gripper_command"
CMD_SET_MODE = "set_mode"
CMD_HEARTBEAT = "heartbeat"
CMD_GET_STATUS = "get_status"
MODE_POSITION = "position"
MODE_TORQUE_OFF = "torque_off"


class SO101DaemonCore:
    def __init__(self, config: SO101DaemonConfig, hardware, *, monotonic=time.monotonic):
        self.config = config
        self.hardware = hardware
        self._monotonic = monotonic
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client_connected = False
        self._last_heartbeat = 0.0
        self._mode = MODE_TORQUE_OFF
        self._watchdog_tripped = False
        self._last_error: str | None = None
        self._q = np.zeros(5, dtype=np.float64)
        self._q_prev = np.zeros(5, dtype=np.float64)
        self._q_vel = np.zeros(5, dtype=np.float64)
        self._target_q = np.zeros(5, dtype=np.float64)
        self._gripper = 0.0
        self._state_time = 0.0
        self._t_mono_ns = 0
        self._voltage_raw: dict[str, int] = {}

    def start(self) -> None:
        self.hardware.connect()
        with self._lock:
            self._update_state_locked(self.hardware.read())
            self._target_q = self._q.copy()
            self.hardware.disable_torque()
            self._mode = MODE_TORQUE_OFF
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._state_loop, name="so101-state-watchdog", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        with self._lock:
            try:
                self.hardware.disable_torque()
            finally:
                self.hardware.disconnect()
                self._mode = MODE_TORQUE_OFF

    def _state_loop(self) -> None:
        interval = 1.0 / self.config.state_rate_hz
        while not self._stop.wait(interval):
            with self._lock:
                try:
                    self._update_state_locked(self.hardware.read())
                    self._enforce_watchdog_locked()
                    self._last_error = None
                except Exception as exc:
                    self._last_error = f"{type(exc).__name__}: {exc}"

    def _update_state_locked(self, observation: dict[str, float]) -> None:
        now = self._monotonic()
        q = np.array(
            [observation[f"{name}.pos"] for name in ARM_JOINT_NAMES],
            dtype=np.float64,
        )
        if self._state_time > 0.0 and now > self._state_time:
            self._q_vel = (q - self._q_prev) / (now - self._state_time)
        self._q_prev = q.copy()
        self._q = q
        self._gripper = float(observation["gripper.pos"])
        self._state_time = now
        self._t_mono_ns = time.monotonic_ns()
        voltage_raw = observation.get("_voltage_raw")
        if isinstance(voltage_raw, dict):
            self._voltage_raw = {
                str(name): int(value)
                for name, value in voltage_raw.items()
            }

    def _lease_alive_locked(self) -> bool:
        timeout = self.config.heartbeat_timeout_ms / 1000.0
        return (
            self._client_connected
            and self._monotonic() - self._last_heartbeat <= timeout
        )

    def _enforce_watchdog_locked(self) -> None:
        if self._mode == MODE_POSITION and not self._lease_alive_locked():
            self.hardware.disable_torque()
            self._mode = MODE_TORQUE_OFF
            self._watchdog_tripped = True

    def handle(self, message: dict) -> dict:
        command = message.get("cmd")
        with self._lock:
            try:
                if command == CMD_CONNECT:
                    self._client_connected = True
                    self._last_heartbeat = self._monotonic()
                    self._watchdog_tripped = False
                    return {
                        "ok": True,
                        "dof": 5,
                        "joint_names": list(ARM_JOINT_NAMES),
                        "resources": ["arm", "gripper"],
                        "mode": self._mode,
                    }
                if command == CMD_DISCONNECT:
                    self._client_connected = False
                    self.hardware.disable_torque()
                    self._mode = MODE_TORQUE_OFF
                    return {"ok": True, "mode": self._mode}
                if command == CMD_HEARTBEAT:
                    if not self._client_connected:
                        return {"ok": False, "error": "no active client lease"}
                    self._last_heartbeat = self._monotonic()
                    return {"ok": True}
                if command == CMD_READ_STATE:
                    return self._state_reply_locked()
                if command == CMD_GET_STATUS:
                    return self._status_reply_locked()
                if command == CMD_SET_MODE:
                    return self._set_mode_locked(str(message.get("mode", "")))
                if command == CMD_SEND_COMMAND:
                    return self._send_arm_locked(
                        message.get("q"), gripper=message.get("gripper")
                    )
                if command == CMD_SEND_GRIPPER_COMMAND:
                    return self._send_gripper_locked(message.get("gripper"))
                return {"ok": False, "error": f"unknown command: {command}"}
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                return {"ok": False, "error": self._last_error}

    def _require_live_position_lease_locked(self) -> str | None:
        self._enforce_watchdog_locked()
        if not self._client_connected:
            return "no active client lease"
        if self._mode != MODE_POSITION:
            return "command requires position mode"
        if not self._lease_alive_locked():
            return "client heartbeat expired"
        return None

    def _set_mode_locked(self, mode: str) -> dict:
        if not self._client_connected:
            return {"ok": False, "error": "no active client lease"}
        if mode == MODE_TORQUE_OFF:
            self.hardware.disable_torque()
            self._mode = MODE_TORQUE_OFF
            return {"ok": True, "mode": self._mode}
        if mode != MODE_POSITION:
            return {"ok": False, "error": f"unknown mode: {mode}"}
        if not self._lease_alive_locked():
            return {"ok": False, "error": "client heartbeat expired"}
        observation = self.hardware.hold_current_and_enable_torque()
        self._update_state_locked(observation)
        self._target_q = self._q.copy()
        self._mode = MODE_POSITION
        self._watchdog_tripped = False
        return {"ok": True, "mode": self._mode}

    def _send_arm_locked(self, values, *, gripper=None) -> dict:
        error = self._require_live_position_lease_locked()
        if error is not None:
            return {"ok": False, "error": error}
        q = np.asarray(values, dtype=np.float64)
        if q.shape != (5,) or not np.isfinite(q).all():
            return {"ok": False, "error": "q must be a finite length-5 vector"}
        limits = self.config.limits
        q = np.clip(q, limits.joint_pos_min_deg, limits.joint_pos_max_deg)
        delta = np.clip(
            q - self._q,
            -limits.max_joint_step_deg,
            limits.max_joint_step_deg,
        )
        applied = self._q + delta
        positions = dict(zip(ARM_JOINT_NAMES, applied))
        applied_gripper = None
        if gripper is not None:
            applied_gripper = float(gripper)
            if not np.isfinite(applied_gripper):
                return {"ok": False, "error": "gripper must be finite"}
            applied_gripper = float(np.clip(
                applied_gripper,
                limits.gripper_min,
                limits.gripper_max,
            ))
            positions["gripper"] = applied_gripper
        self.hardware.send(positions)
        self._target_q = applied.copy()
        reply = {"ok": True, "applied_q": applied.tolist()}
        if applied_gripper is not None:
            reply["applied_gripper"] = applied_gripper
        return reply

    def _send_gripper_locked(self, value) -> dict:
        error = self._require_live_position_lease_locked()
        if error is not None:
            return {"ok": False, "error": error}
        gripper = float(value)
        if not np.isfinite(gripper):
            return {"ok": False, "error": "gripper must be finite"}
        gripper = float(np.clip(
            gripper,
            self.config.limits.gripper_min,
            self.config.limits.gripper_max,
        ))
        self.hardware.send({"gripper": gripper})
        return {"ok": True, "applied_gripper": gripper}

    def _state_reply_locked(self) -> dict:
        return {
            "ok": True,
            "joint_pos": self._q.tolist(),
            "joint_vel": self._q_vel.tolist(),
            "joint_effort": [0.0] * 5,
            "target_joint_pos": self._target_q.tolist(),
            "gripper_pos": self._gripper,
            "t_mono_ns": self._t_mono_ns,
            "mode": self._mode,
        }

    def _status_reply_locked(self) -> dict:
        return {
            "ok": True,
            "mode": self._mode,
            "client_connected": self._client_connected,
            "lease_alive": self._lease_alive_locked(),
            "watchdog_tripped": self._watchdog_tripped,
            "last_error": self._last_error,
            "target_joint_pos": self._target_q.tolist(),
            "voltage_raw": dict(self._voltage_raw),
        }
