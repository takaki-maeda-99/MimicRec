"""Mode controllers for the reBotArm daemon: POSITION and GRAVITY_COMP.

Both controllers are designed to be called from the 500 Hz control
callback (``RobotArm.start_control_loop``). They own no threads of
their own; they only read state from ``arm`` and issue ``arm.mit(...)``
or ``arm.pos_vel(...)`` commands.

API names verified against ``reBotArm_control_py``:
- ``compute_generalized_gravity(q=...)`` — dynamics/inverse_dynamics.py
- ``arm.mit(pos, vel, kp, kd, tau, request_feedback)`` — actuator/arm.py
- ``arm.pos_vel(pos, vlim=...)`` — actuator/arm.py (NB: 2nd arg is
  velocity *limit*, not setpoint)
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
        tau_g = compute_generalized_gravity(q=q)
        if self._safety is not None:
            tau_g = self._safety.clamp_torque(tau_g)
        arm.mit(
            pos=q,
            vel=np.zeros(self._n),
            kp=np.asarray(self._params.kp, dtype=float),
            kd=np.asarray(self._params.kd, dtype=float),
            tau=tau_g,
            request_feedback=True,
        )


class PositionController:
    """POS_VEL position controller — sends a held target each tick.

    The arm itself must already be in POS_VEL mode (``arm.mode_pos_vel()``)
    when ``step`` is invoked; ``server.py`` handles the mode switch.
    ``vlim`` is left at the per-joint default baked into the arm config.
    """

    def __init__(self, num_joints: int):
        self._n = num_joints
        self._target: np.ndarray | None = None

    def set_target(self, q: np.ndarray) -> None:
        self._target = np.asarray(q, dtype=float).copy()

    def reset(self) -> None:
        self._target = None

    def step(self, arm) -> None:
        if self._target is None:
            self._target = arm.get_positions().copy()
        arm.pos_vel(pos=self._target)
