"""Multi-layer safety for the reBotArm daemon.

Pure-Python (numpy) — no motorbridge imports — so it can be unit-tested
in the 3.12 venv even though the daemon runs under 3.10.
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from rebotarm_daemon.config import SafetyLimits


_OK = "ok"
_WARN = "warn"
_ESTOP = "estop"
_HEARTBEAT_TIMEOUT = "heartbeat_timeout"
_THERMAL_FAULT = "thermal_fault"
_TORQUE_FAULT = "torque_fault"


class SafetyManager:
    def __init__(self, limits: SafetyLimits, dof: int = 6):
        self._limits = limits
        self._dof = dof

        # state-machine: latched faults (cleared only via try_clear_estop)
        self._estop_active = False
        self._thermal_active = False
        self._torque_active = False

        # last heartbeat timestamp (monotonic seconds); initialized far in past
        self._last_hb_t: float = 0.0

        # rolling for accel ramp
        self._last_q: Optional[np.ndarray] = None

    # ---- clamps -------------------------------------------------------

    def clamp_joint_pos(self, q: np.ndarray) -> np.ndarray:
        lo = np.asarray(self._limits.joint_pos_min_rad, dtype=float)
        hi = np.asarray(self._limits.joint_pos_max_rad, dtype=float)
        return np.clip(q, lo, hi).astype(q.dtype)

    def ramp_velocity(self, q_now: np.ndarray, q_target: np.ndarray, dt: float) -> np.ndarray:
        if dt <= 0:
            return q_now.copy()
        max_step = self._limits.joint_vel_max_rad_s * dt
        delta = q_target - q_now
        norm = np.abs(delta)
        scale = np.where(norm > max_step, max_step / np.maximum(norm, 1e-12), 1.0)
        return q_now + delta * scale

    def ramp_accel(self, q_target: np.ndarray, dt: float) -> np.ndarray:
        if self._last_q is None or dt <= 0:
            self._last_q = q_target.copy()
            return q_target
        max_step = self._limits.joint_accel_max_rad_s2 * dt * dt
        delta = q_target - self._last_q
        norm = np.abs(delta)
        scale = np.where(norm > max_step, max_step / np.maximum(norm, 1e-12), 1.0)
        out = self._last_q + delta * scale
        self._last_q = out.copy()
        return out

    def clamp_torque(self, tau: np.ndarray) -> np.ndarray:
        bound = np.asarray(self._limits.torque_max_nm, dtype=float)
        return np.clip(tau, -bound, bound).astype(tau.dtype)

    # ---- heartbeat ---------------------------------------------------

    def note_heartbeat(self) -> None:
        self._last_hb_t = time.monotonic()

    def heartbeat_state(self, now_t: Optional[float] = None) -> str:
        if self._last_hb_t == 0.0:
            return _OK  # no heartbeats expected yet (pre-connect)
        now = time.monotonic() if now_t is None else now_t
        age_ms = (now - self._last_hb_t) * 1000.0
        if age_ms > self._limits.heartbeat_timeout_ms:
            return _HEARTBEAT_TIMEOUT
        return _OK

    # ---- thermal -----------------------------------------------------

    def evaluate_thermal(self, temps_c: np.ndarray) -> str:
        max_t = float(np.max(temps_c))
        if self._thermal_active:
            return _THERMAL_FAULT
        if max_t >= self._limits.temperature_fault_c:
            self._thermal_active = True
            return _THERMAL_FAULT
        if max_t >= self._limits.temperature_warn_c:
            return _WARN
        return _OK

    # ---- estop / fault state ----------------------------------------

    def reset_ramp_state(self) -> None:
        """Forget the accel-ramp's running ``_last_q``.

        Called when entering POSITION mode so the first incoming command
        is evaluated against the real measured pose, not whatever target
        the ramp tracked the last time POSITION was active.
        """
        self._last_q = None

    def trigger_estop(self) -> None:
        self._estop_active = True

    def trigger_torque_fault(self) -> None:
        self._torque_active = True

    def is_active_fault(self) -> bool:
        return self._estop_active or self._thermal_active or self._torque_active

    def try_clear_estop(self, current_temps_c: np.ndarray) -> bool:
        """Try to clear ALL latched faults (estop + thermal + torque).

        The name is "estop" because the externally-visible recovery action
        is "operator clears E-stop" — but a single try_clear_estop call
        gates on every fault source, since they share the same recovery
        procedure: confirm the robot is in a safe state and resume.

        Returns True if all gates pass and faults were cleared:
          - max temp < temperature_recover_c
          - heartbeat is fresh (heartbeat_state == OK)
          - (no torque-fault-specific gate today; it clears alongside the others)
        """
        if float(np.max(current_temps_c)) >= self._limits.temperature_recover_c:
            return False
        if self.heartbeat_state() != _OK:
            return False
        # torque faults clear automatically once cleared
        self._estop_active = False
        self._thermal_active = False
        self._torque_active = False
        return True

    # ---- aggregate state for status payload --------------------------

    def overall_state(self, temps_c: Optional[np.ndarray] = None) -> str:
        """Aggregate the current fault / warning state for status payloads.

        Side effect: when ``temps_c`` is provided, this calls
        :meth:`evaluate_thermal`, which can latch ``_thermal_active``. That's
        intentional — a robot whose temperature crossed the fault threshold
        must be considered faulted, even if the read happened during a
        "status check" rather than the main control loop. Callers that want
        a non-mutating read should pass ``temps_c=None``.
        """
        # priority: estop > thermal > torque > heartbeat > warn > ok
        if self._estop_active:
            return _ESTOP
        if self._thermal_active:
            return _THERMAL_FAULT
        if self._torque_active:
            return _TORQUE_FAULT
        hb = self.heartbeat_state()
        if hb != _OK:
            return hb
        if temps_c is not None:
            warn = self.evaluate_thermal(temps_c)
            if warn != _OK:
                return warn
        return _OK
