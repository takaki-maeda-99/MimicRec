from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
import numpy as np
from scipy.spatial.transform import Rotation as R

from mimicrec.inference.contract import ContractSpec, _expected_dim
from mimicrec.inference.types import StepAction
from mimicrec.types import RobotState


class FKLike(Protocol):
    def matrix(self, q: np.ndarray) -> np.ndarray: ...


class IKLike(Protocol):
    def solve(self, T: np.ndarray, seed: np.ndarray) -> tuple[np.ndarray, bool]: ...


def _to_T(pos: np.ndarray, axisangle: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, 3] = pos
    if np.linalg.norm(axisangle) > 1e-9:
        T[:3, :3] = R.from_rotvec(axisangle).as_matrix()
    return T


@dataclass
class ActionDecoder:
    spec: ContractSpec
    fk: FKLike
    ik: IKLike
    narm: int
    # action_stats: dict with `mean` (list[float]) and `std` (list[float]) of length
    # equal to sum(action.components dims), or None when normalization=='none'.
    # Lifecycle (Task 16) wires this from `contract.resolve_action_stats()`.
    action_stats: dict | None = None

    def __post_init__(self) -> None:
        method = self.spec.response.action.normalization.method
        if method == "none":
            self._action_mean = None
            self._action_std = None
        elif method in ("mean_std", "minmax_neg1_pos1"):
            if self.action_stats is None:
                raise ValueError(
                    f"action_stats required when normalization.method='{method}'"
                )
            self._action_mean = np.asarray(self.action_stats["mean"], dtype=np.float64)
            self._action_std = np.asarray(self.action_stats["std"], dtype=np.float64)
        else:
            # Unknown method — defer the error to decode() so the guard in
            # _de_normalize fires with the expected "normalization" match string.
            self._action_mean = None
            self._action_std = None

    def _de_normalize(self, arr: np.ndarray) -> np.ndarray:
        """Convert a normalized action vector to physical units.
        For BOTH `mean_std` and `minmax_neg1_pos1` we apply `physical = mean + arr * std`:
          - mean_std: stats hold population mean/std -> straightforward.
          - minmax_neg1_pos1: by convention, stats encode midpoint (mean) and
            half-range (std), so arr in [-1, +1] maps to [mean-std, mean+std].
            See `vla_compat/stats.py` for how stats are produced.
        Servers that already produce physical units should set
        `normalization.method: none` in their contract."""
        method = self.spec.response.action.normalization.method
        if method == "none":
            return arr
        if method in ("mean_std", "minmax_neg1_pos1"):
            return self._action_mean + arr * self._action_std
        raise ValueError(f"unknown normalization.method: '{method}'")

    def decode(self, response_body: dict, current_state: RobotState) -> list[StepAction]:
        actions = self._extract_actions(response_body)
        expected_action_dim = _expected_dim(self.spec.response.action.components)
        seed_q = current_state.joint_pos[:self.narm].copy()
        T_curr = self.fk.matrix(seed_q)
        chunk: list[StepAction] = []
        for raw in actions:
            if len(raw) != expected_action_dim:
                raise ValueError(
                    f"action row length {len(raw)} != expected {expected_action_dim} "
                    f"from components {self.spec.response.action.components}"
                )
            arr = np.asarray(raw, dtype=np.float64)
            arr_phys = self._de_normalize(arr)             # <- critical: de-normalize FIRST
            ee_delta_phys = arr_phys[:6]
            gripper_raw = float(arr_phys[6]) if arr_phys.shape[0] >= 7 else None
            # pose.units is validated to "meter_axisangle_rad" at contract load time.
            pos = ee_delta_phys[:3]
            axisangle = ee_delta_phys[3:6]
            T_delta = _to_T(pos, axisangle)
            if self.spec.response.action.frame == "ee_local":
                T_next = T_curr @ T_delta
            else:
                T_next = T_delta @ T_curr
            q_next, ok = self.ik.solve(T_next, seed=seed_q)
            if not ok:
                # IK failed: hold the seed AND revert T_curr to the FK of the
                # seed so subsequent chunk steps chain from the achievable
                # pose, not from the fictional `T_next` we couldn't reach.
                # Without this, repeated IK failures compound the drift
                # between the model's intended pose and the actual robot
                # pose, producing wildly off-target later targets.
                q_next = seed_q
                T_curr = self.fk.matrix(seed_q)
            else:
                # Chain step N+1 from the pose the robot will actually reach,
                # not the idealized T_next. IK may converge approximately;
                # using T_next compounds residuals across the 8-step chunk.
                T_curr = self.fk.matrix(q_next)
            gripper_cmd = self._decode_gripper(gripper_raw, current_state.gripper_pos)
            chunk.append(StepAction(q=q_next, gripper=gripper_cmd, ik_failed=not ok))
            seed_q = q_next
        return chunk

    def _extract_actions(self, body: dict) -> list:
        path = self.spec.response.actions_path
        node = body
        for key in path.split("."):
            node = node[key]
        return node

    def _decode_gripper(self, raw: float | None, current: float | None) -> float | None:
        if raw is None:
            return None
        kind = self.spec.response.action.gripper.kind
        if kind == "absolute":
            return raw
        if kind == "delta":
            return (current or 0.0) + raw
        if kind == "binary":
            return 1.0 if raw >= 0.5 else 0.0
        raise ValueError(f"unknown gripper.kind: {kind}")
