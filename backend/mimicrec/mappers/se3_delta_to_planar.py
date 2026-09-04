"""Projection of the common SE3Delta action onto a planar mobile base."""
from __future__ import annotations

from typing import Mapping

import numpy as np

from mimicrec.motion.types import (
    MotionStep,
    PlanarVelocityCommand,
    ResourceCommand,
    ResourceState,
)


class SE3DeltaToPlanarBaseMapper:
    def __init__(
        self,
        *,
        drive_resource: str = "mobile_base.drive",
        holonomic: bool = False,
        max_linear_velocity_m_s: float = 0.5,
        max_angular_velocity_rad_s: float = 1.0,
    ) -> None:
        self.drive_resource = drive_resource
        self.holonomic = bool(holonomic)
        self.max_linear_velocity = float(max_linear_velocity_m_s)
        self.max_angular_velocity = float(max_angular_velocity_rad_s)
        if self.max_linear_velocity <= 0 or self.max_angular_velocity <= 0:
            raise ValueError("planar velocity limits must be > 0")
        self._last_discarded_norm = 0.0

    def map(
        self,
        step: MotionStep,
        resource_states: Mapping[str, ResourceState],
    ) -> Mapping[str, ResourceCommand]:
        velocity = step.delta.as_velocity()
        planar = np.array(
            [velocity[0], velocity[1] if self.holonomic else 0.0, velocity[5]],
            dtype=np.float64,
        )
        linear_norm = float(np.linalg.norm(planar[:2]))
        if linear_norm > self.max_linear_velocity:
            planar[:2] *= self.max_linear_velocity / linear_norm
        planar[2] = np.clip(
            planar[2], -self.max_angular_velocity, self.max_angular_velocity
        )
        represented = np.array(
            [planar[0], planar[1], 0.0, 0.0, 0.0, planar[2]],
            dtype=np.float64,
        )
        self._last_discarded_norm = float(np.linalg.norm(velocity - represented))
        return {
            self.drive_resource: PlanarVelocityCommand(
                planar.astype(np.float32), t_mono_ns=step.t_mono_ns
            )
        }

    def telemetry(self) -> dict[str, float]:
        return {"discarded_twist_velocity_norm": self._last_discarded_norm}
