"""SE(3) increments used as MimicRec's embodiment-independent action.

The six-vector convention is ``[rho_x, rho_y, rho_z, phi_x, phi_y, phi_z]``
where ``rho`` and ``phi`` are the translational and rotational coordinates of
the matrix logarithm.  This distinction matters when rotation and translation
occur in the same step: ``rho`` is not generally equal to the translation
column of the resulting transform.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

import numpy as np
from scipy.spatial.transform import Rotation


class SE3Frame(str, Enum):
    """Frame in which an increment is expressed."""

    EE_LOCAL = "ee_local"
    BASE = "base"
    WORLD = "world"


def _skew(vector: np.ndarray) -> np.ndarray:
    x, y, z = vector
    return np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])


def se3_exp(tangent: np.ndarray | Iterable[float]) -> np.ndarray:
    """Map a six-dimensional tangent vector to a homogeneous transform."""

    xi = np.asarray(tangent, dtype=np.float64)
    if xi.shape != (6,) or not np.isfinite(xi).all():
        raise ValueError("SE(3) tangent must be a finite length-6 vector")
    rho = xi[:3]
    phi = xi[3:]
    theta = float(np.linalg.norm(phi))
    phi_hat = _skew(phi)
    phi_hat_sq = phi_hat @ phi_hat
    if theta < 1e-8:
        left_jacobian = np.eye(3) + 0.5 * phi_hat + phi_hat_sq / 6.0
    else:
        theta_sq = theta * theta
        left_jacobian = (
            np.eye(3)
            + ((1.0 - np.cos(theta)) / theta_sq) * phi_hat
            + ((theta - np.sin(theta)) / (theta_sq * theta)) * phi_hat_sq
        )
    transform = np.eye(4, dtype=np.float64)
    # scipy's Cython buffer wrapper rejects a read-only view. SE3Delta makes
    # its public array immutable, so take a tiny writable copy here.
    transform[:3, :3] = Rotation.from_rotvec(phi.copy()).as_matrix()
    transform[:3, 3] = left_jacobian @ rho
    return transform


def se3_log(transform: np.ndarray) -> np.ndarray:
    """Map a homogeneous transform to its shortest six-vector logarithm."""

    matrix = np.asarray(transform, dtype=np.float64)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError("SE(3) transform must be a finite 4x4 matrix")
    if not np.allclose(matrix[3], (0.0, 0.0, 0.0, 1.0), atol=1e-8):
        raise ValueError("invalid homogeneous transform bottom row")
    rotation = matrix[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6):
        raise ValueError("SE(3) rotation block must be orthonormal")
    if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-6):
        raise ValueError("SE(3) rotation block must have determinant +1")

    phi = Rotation.from_matrix(rotation).as_rotvec()
    theta = float(np.linalg.norm(phi))
    phi_hat = _skew(phi)
    phi_hat_sq = phi_hat @ phi_hat
    if theta < 1e-8:
        left_jacobian_inv = np.eye(3) - 0.5 * phi_hat + phi_hat_sq / 12.0
    else:
        theta_sq = theta * theta
        coefficient = (
            1.0 / theta_sq
            - (1.0 + np.cos(theta)) / (2.0 * theta * np.sin(theta))
        )
        left_jacobian_inv = np.eye(3) - 0.5 * phi_hat + coefficient * phi_hat_sq
    rho = left_jacobian_inv @ matrix[:3, 3]
    return np.concatenate((rho, phi)).astype(np.float64)


@dataclass(frozen=True)
class SE3Delta:
    """One control-step displacement in SE(3), never an implicit velocity."""

    tangent: np.ndarray
    frame: SE3Frame | str = SE3Frame.EE_LOCAL
    duration_sec: float = 1.0 / 60.0
    active_mask: np.ndarray = field(
        default_factory=lambda: np.ones(6, dtype=np.bool_)
    )

    def __post_init__(self) -> None:
        tangent = np.asarray(self.tangent, dtype=np.float64).copy()
        mask = np.asarray(self.active_mask, dtype=np.bool_).copy()
        if tangent.shape != (6,) or not np.isfinite(tangent).all():
            raise ValueError("SE3Delta.tangent must be a finite length-6 vector")
        if mask.shape != (6,):
            raise ValueError("SE3Delta.active_mask must be a length-6 vector")
        duration = float(self.duration_sec)
        if not np.isfinite(duration) or duration <= 0.0:
            raise ValueError("SE3Delta.duration_sec must be finite and > 0")
        tangent[~mask] = 0.0
        tangent.setflags(write=False)
        mask.setflags(write=False)
        object.__setattr__(self, "tangent", tangent)
        object.__setattr__(self, "active_mask", mask)
        object.__setattr__(self, "frame", SE3Frame(self.frame))
        object.__setattr__(self, "duration_sec", duration)

    @classmethod
    def identity(
        cls,
        *,
        frame: SE3Frame | str = SE3Frame.EE_LOCAL,
        duration_sec: float = 1.0 / 60.0,
        active_mask: np.ndarray | None = None,
    ) -> "SE3Delta":
        return cls(
            tangent=np.zeros(6),
            frame=frame,
            duration_sec=duration_sec,
            active_mask=(np.ones(6, dtype=np.bool_) if active_mask is None else active_mask),
        )

    @classmethod
    def from_transform(
        cls,
        transform: np.ndarray,
        *,
        frame: SE3Frame | str = SE3Frame.EE_LOCAL,
        duration_sec: float = 1.0 / 60.0,
        active_mask: np.ndarray | None = None,
    ) -> "SE3Delta":
        return cls(
            tangent=se3_log(transform),
            frame=frame,
            duration_sec=duration_sec,
            active_mask=(np.ones(6, dtype=np.bool_) if active_mask is None else active_mask),
        )

    @classmethod
    def from_velocity(
        cls,
        velocity: np.ndarray | Iterable[float],
        *,
        duration_sec: float,
        frame: SE3Frame | str = SE3Frame.EE_LOCAL,
        active_mask: np.ndarray | None = None,
    ) -> "SE3Delta":
        return cls(
            tangent=np.asarray(velocity, dtype=np.float64) * duration_sec,
            frame=frame,
            duration_sec=duration_sec,
            active_mask=(np.ones(6, dtype=np.bool_) if active_mask is None else active_mask),
        )

    def as_transform(self) -> np.ndarray:
        return se3_exp(self.tangent)

    def as_velocity(self) -> np.ndarray:
        return self.tangent.copy() / self.duration_sec

    def resample(self, duration_sec: float) -> "SE3Delta":
        """Preserve average twist while changing the action step duration."""

        return SE3Delta.from_velocity(
            self.as_velocity(),
            duration_sec=duration_sec,
            frame=self.frame,
            active_mask=self.active_mask,
        )


def compose_deltas(deltas: Iterable[SE3Delta]) -> SE3Delta:
    """Compose ordered increments without incorrectly adding tangent vectors."""

    items = list(deltas)
    if not items:
        raise ValueError("compose_deltas requires at least one increment")
    frame = items[0].frame
    if any(item.frame != frame for item in items):
        raise ValueError("cannot compose SE3Delta values expressed in different frames")
    transform = np.eye(4)
    mask = np.zeros(6, dtype=np.bool_)
    duration = 0.0
    for item in items:
        transform = transform @ item.as_transform()
        mask |= item.active_mask
        duration += item.duration_sec
    return SE3Delta.from_transform(
        transform,
        frame=frame,
        duration_sec=duration,
        active_mask=mask,
    )
