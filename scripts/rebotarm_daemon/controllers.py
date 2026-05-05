"""Mode controllers for the reBotArm daemon: POSITION and GRAVITY_COMP.

Both controllers stay in MIT mode at the motor level. The daemon's
"GRAVITY_COMP" is MIT with kp=0 + tau_g feed-forward; "POSITION" is MIT
with strong kp + tau_g. Mode transitions only swap kp/kd between the
two profiles per-tick — the underlying motors never leave MIT, which
means we never pay the ~200 ms torque-dropout-per-motor that
``arm.mode_pos_vel()`` causes (and which used to drop the arm under
gravity whenever a replay flipped modes).

API names verified against ``reBotArm_control_py``:
- ``compute_generalized_gravity(q=...)`` — dynamics/inverse_dynamics.py
- ``arm.mit(pos, vel, kp, kd, tau, request_feedback)`` — actuator/arm.py
- ``arm.get_positions()`` — actuator/arm.py
"""
from __future__ import annotations

import numpy as np

from reBotArm_control_py.dynamics import (
    compute_generalized_gravity,
    load_dynamics_model,
)


class GravityCompController:
    """Pure-compliance gravity comp — kp=0, per-joint kd, tau_g feed-forward.

    Mirrors reBotArm_control_py/data_collect/11_gravity_compensation_record.py:
    every tick we send ``pos=q``, ``vel=0``, the configured kp/kd, and
    Pinocchio's gravity-balance torque. With kp=0 the arm offers no
    position-hold force; per-joint kd (higher on the proximal 4340P
    joints) damps oscillation so the arm settles instead of "flying away"
    when released.
    """

    def __init__(self, params, num_joints: int, safety=None):
        self._params = params
        self._n = num_joints
        # Warm the dynamics-model cache so the first control tick doesn't
        # pay the URDF parse cost. compute_generalized_gravity also caches
        # internally; this just makes the dependency explicit.
        self._dyn_model = load_dynamics_model()
        # Optional SafetyManager — when provided, tau_g is run through
        # clamp_torque() before being fed to arm.mit() so a runaway
        # gravity feed-forward can't issue an out-of-bounds torque.
        self._safety = safety

    def reset(self) -> None:
        # No internal state under pure compliance; kept for API symmetry
        # with PositionController.reset().
        pass

    def step(self, arm) -> None:
        q = arm.get_positions()
        qdot = arm.get_velocities()
        tau_g = compute_generalized_gravity(q=q)
        friction_tau = np.asarray(self._params.friction_tau_nm, dtype=float)
        deadband = np.asarray(self._params.vel_deadband_rad_s, dtype=float)
        # sign(qdot) gated by per-joint deadband — zero inside
        # [-deadband[i], +deadband[i]] so we don't chatter at standstill.
        sign = np.where(np.abs(qdot) > deadband, np.sign(qdot), 0.0)
        tau = tau_g + friction_tau * sign
        if self._safety is not None:
            tau = self._safety.clamp_torque(tau)
        arm.mit(
            pos=q,
            vel=np.zeros(self._n),
            kp=np.asarray(self._params.kp, dtype=float),
            kd=np.asarray(self._params.kd, dtype=float),
            tau=tau,
            request_feedback=True,
        )


class PositionController:
    """MIT-mode position tracker — strong kp/kd + gravity FF.

    Holds the latest commanded target with the configured per-joint kp/kd.
    Gravity FF reduces the position error needed to support the arm's
    weight, so kp can be lower than it would have to be without FF.

    Stays in MIT throughout — same motor-level mode as GRAVITY_COMP. Mode
    swaps in the daemon are pure software: ``server.py`` flips which
    controller's ``step()`` runs, and the only thing the motor sees is
    different kp/kd/pos/tau values per tick. No mode-transition torque
    dropout.
    """

    def __init__(self, params, num_joints: int, safety=None):
        self._params = params
        self._n = num_joints
        self._dyn_model = load_dynamics_model()
        self._safety = safety
        self._target: np.ndarray | None = None

    def set_target(self, q: np.ndarray) -> None:
        self._target = np.asarray(q, dtype=float).copy()

    def reset(self) -> None:
        self._target = None

    def step(self, arm) -> None:
        q = arm.get_positions()
        if self._target is None:
            self._target = q.copy()
        tau_g = compute_generalized_gravity(q=q)
        if self._safety is not None:
            tau_g = self._safety.clamp_torque(tau_g)
        arm.mit(
            pos=self._target,
            vel=np.zeros(self._n),
            kp=np.asarray(self._params.kp, dtype=float),
            kd=np.asarray(self._params.kd, dtype=float),
            tau=tau_g,
            request_feedback=True,
        )
