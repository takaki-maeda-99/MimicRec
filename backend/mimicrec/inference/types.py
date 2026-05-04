from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import numpy as np


SafetyKind = Literal["delta_clamp", "joint_limit", "slow_stop", "ik_fail"]


@dataclass
class StepAction:
    """One step of decoded action: target joints (degrees) + optional gripper.
    `ik_failed=True` when IK could not solve for this step (caller used the seed).
    """
    q: np.ndarray
    gripper: float | None
    ik_failed: bool = False


@dataclass
class SafetyEvent:
    kind: SafetyKind
    step_index: int | None = None
    joint: str | None = None

    def as_dict(self) -> dict:
        d: dict = {"type": "safety_event", "kind": self.kind}
        if self.step_index is not None:
            d["step_index"] = self.step_index
        if self.joint is not None:
            d["joint"] = self.joint
        return d
