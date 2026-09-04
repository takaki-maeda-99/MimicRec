"""Decode policy chunks directly into the common MotionStep token stream."""
from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from mimicrec.inference.contract import ContractSpec, _expected_dim
from mimicrec.motion.se3 import SE3Delta, SE3Frame
from mimicrec.motion.types import MotionStep


class MotionActionDecoder:
    def __init__(
        self,
        spec: ContractSpec,
        *,
        duration_sec: float,
        action_stats: dict | None = None,
    ) -> None:
        self.spec = spec
        self.duration_sec = float(duration_sec)
        if self.duration_sec <= 0.0:
            raise ValueError("motion inference duration_sec must be > 0")
        self.action_stats = action_stats
        self._gripper = 0.0

    def decode(self, response_body: dict) -> list[MotionStep]:
        node = response_body
        for key in self.spec.response.actions_path.split("."):
            node = node[key]
        rows = list(node)
        chunk = self.spec.response.chunk
        if chunk.on_size_mismatch == "reject" and len(rows) != chunk.expected_size:
            raise ValueError(
                f"chunk size {len(rows)} != expected {chunk.expected_size}"
            )
        expected = _expected_dim(self.spec.response.action.components)
        result = []
        for row in rows:
            values = np.asarray(row, dtype=np.float64)
            if values.shape != (expected,) or not np.isfinite(values).all():
                raise ValueError(
                    f"motion action row must be a finite ({expected},) vector"
                )
            values = self._denormalize(values)
            tangent = self._to_log_increment(values[:6])
            auxiliary = {}
            if values.size > 6:
                auxiliary["gripper"] = self._decode_gripper(float(values[6]))
            frame = (
                SE3Frame.EE_LOCAL
                if self.spec.response.action.frame == "ee_local"
                else SE3Frame.WORLD
            )
            result.append(MotionStep(
                delta=SE3Delta(
                    tangent,
                    frame=frame,
                    duration_sec=self.duration_sec,
                ),
                auxiliary=auxiliary,
            ))
        return result

    def _denormalize(self, values: np.ndarray) -> np.ndarray:
        method = self.spec.response.action.normalization.method
        if method == "none":
            return values
        if self.action_stats is None:
            raise ValueError(f"action stats required for {method}")
        mean = np.asarray(self.action_stats["mean"], dtype=np.float64)
        std = np.asarray(self.action_stats["std"], dtype=np.float64)
        return mean + values * std

    def _to_log_increment(self, pose: np.ndarray) -> np.ndarray:
        if self.spec.response.action.pose.units == "se3_log_increment":
            return pose.copy()
        transform = np.eye(4)
        transform[:3, 3] = pose[:3]
        transform[:3, :3] = Rotation.from_rotvec(pose[3:].copy()).as_matrix()
        return SE3Delta.from_transform(
            transform, duration_sec=self.duration_sec
        ).tangent.copy()

    def _decode_gripper(self, value: float) -> float:
        kind = self.spec.response.action.gripper.kind
        if kind == "delta":
            self._gripper += value
        elif kind == "binary":
            self._gripper = 1.0 if value >= 0.5 else 0.0
        else:
            self._gripper = value
        self._gripper = float(np.clip(self._gripper, 0.0, 1.0))
        return self._gripper
