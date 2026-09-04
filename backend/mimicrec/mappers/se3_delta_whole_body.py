"""Generic damped weighted-Jacobian mapper for whole-body control."""
from __future__ import annotations

import importlib
from typing import Mapping, Protocol

import numpy as np

from mimicrec.motion.types import MotionStep, ResourceCommand, ResourceState


class WholeBodyModel(Protocol):
    """Robot-specific Jacobian and command packing behind common SE3Delta."""

    def jacobian(self, states: Mapping[str, ResourceState]) -> np.ndarray: ...

    def commands(
        self,
        generalized_velocity: np.ndarray,
        step: MotionStep,
        states: Mapping[str, ResourceState],
    ) -> Mapping[str, ResourceCommand]: ...


def _load_model(target: str, kwargs: dict) -> WholeBodyModel:
    module_name, class_name = target.rsplit(".", 1)
    model_class = getattr(importlib.import_module(module_name), class_name)
    return model_class(**kwargs)


class SE3DeltaWholeBodyMapper:
    """Map one Cartesian increment across any coupled mechanism.

    A model supplies the stacked whole-body Jacobian and translates the solved
    generalized velocity into commands for one or more named resources. This
    keeps mobile-base/arm combinations outside the core runtime.
    """

    def __init__(
        self,
        *,
        model: WholeBodyModel | None = None,
        model_target: str | None = None,
        model_kwargs: dict | None = None,
        task_weights: list[float] | None = None,
        damping: float = 0.02,
        max_generalized_velocity: list[float] | None = None,
    ) -> None:
        if model is None:
            if model_target is None:
                raise ValueError("whole-body mapper requires model or model_target")
            model = _load_model(model_target, model_kwargs or {})
        self.model = model
        self.task_weights = np.asarray(
            task_weights or [1.0] * 6, dtype=np.float64
        )
        if self.task_weights.shape != (6,) or np.any(self.task_weights < 0):
            raise ValueError("task_weights must contain six non-negative values")
        self.damping = float(damping)
        if self.damping <= 0.0:
            raise ValueError("damping must be > 0")
        self.max_generalized_velocity = (
            None
            if max_generalized_velocity is None
            else np.asarray(max_generalized_velocity, dtype=np.float64)
        )
        self._last_residual_norm = 0.0

    def map(
        self,
        step: MotionStep,
        resource_states: Mapping[str, ResourceState],
    ) -> Mapping[str, ResourceCommand]:
        jacobian = np.asarray(
            self.model.jacobian(resource_states), dtype=np.float64
        )
        if jacobian.ndim != 2 or jacobian.shape[0] != 6:
            raise ValueError("whole-body Jacobian must have shape (6, n)")
        if not np.isfinite(jacobian).all():
            raise ValueError("whole-body Jacobian contains non-finite values")
        target = step.delta.as_velocity()
        active_weights = self.task_weights * step.delta.active_mask.astype(float)
        active = active_weights > 0.0
        if not np.any(active):
            generalized = np.zeros(jacobian.shape[1], dtype=np.float64)
        else:
            weight_sqrt = np.sqrt(active_weights[active])
            weighted_jacobian = jacobian[active] * weight_sqrt[:, None]
            weighted_target = target[active] * weight_sqrt
            normal = (
                weighted_jacobian @ weighted_jacobian.T
                + (self.damping**2) * np.eye(int(np.sum(active)))
            )
            generalized = weighted_jacobian.T @ np.linalg.solve(
                normal, weighted_target
            )
        if self.max_generalized_velocity is not None:
            if self.max_generalized_velocity.shape != generalized.shape:
                raise ValueError(
                    "max_generalized_velocity length does not match Jacobian columns"
                )
            generalized = np.clip(
                generalized,
                -self.max_generalized_velocity,
                self.max_generalized_velocity,
            )
        self._last_residual_norm = float(
            np.linalg.norm((jacobian @ generalized - target)[active])
            if np.any(active)
            else 0.0
        )
        commands = dict(
            self.model.commands(generalized, step, resource_states)
        )
        if not commands:
            raise ValueError("whole-body model emitted no resource commands")
        return commands

    def telemetry(self) -> dict[str, float]:
        return {"whole_body_twist_residual_norm": self._last_residual_norm}
