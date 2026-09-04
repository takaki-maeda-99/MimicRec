"""Pure clutch-relative SE(3) math used by the ROS 2 bridge."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True)
class Pose:
    position: tuple[float, float, float]
    orientation_xyzw: tuple[float, float, float, float]


@dataclass(frozen=True)
class PoseOffset:
    translation: tuple[float, float, float]
    rotation_rotvec: tuple[float, float, float]
    control_rotation_rotvec: tuple[float, float, float] | None = None

    def as_list(self) -> list[float]:
        return [*self.translation, *self.rotation_rotvec]


def world_offset_step(previous: PoseOffset, current: PoseOffset) -> PoseOffset:
    """Differentiate absolute WORLD offsets without rotating their origin.

    Translation is the displacement of the tracked controller point. Rotation
    is the spatial/world rotation increment. Keeping these components separate
    prevents a pure rotation from orbiting the robot EEF around the world
    origin when the action is retargeted to another embodiment.
    """

    previous_q = _rotvec_to_quaternion(previous.rotation_rotvec)
    current_q = _rotvec_to_quaternion(current.rotation_rotvec)
    relative_q = _quaternion_multiply(
        current_q, _quaternion_conjugate(previous_q)
    )
    return PoseOffset(
        translation=tuple(
            current.translation[index] - previous.translation[index]
            for index in range(3)
        ),
        rotation_rotvec=_quaternion_to_rotvec(relative_q),
    )


def _finite(values: Sequence[float]) -> bool:
    return all(math.isfinite(float(value)) for value in values)


def _normalize_quaternion(
    value: Sequence[float],
) -> tuple[float, float, float, float] | None:
    if len(value) != 4 or not _finite(value):
        return None
    norm = math.sqrt(sum(float(component) ** 2 for component in value))
    if norm < 1e-9:
        return None
    return tuple(float(component) / norm for component in value)  # type: ignore[return-value]


def _quaternion_multiply(
    left: Sequence[float], right: Sequence[float]
) -> tuple[float, float, float, float]:
    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return (
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    )


def _quaternion_conjugate(
    value: Sequence[float],
) -> tuple[float, float, float, float]:
    x, y, z, w = value
    return (-x, -y, -z, w)


def compose_pose(parent: Pose, child: Pose) -> Pose:
    """Compose parent->intermediate and intermediate->child poses."""

    parent_q = _normalize_quaternion(parent.orientation_xyzw)
    child_q = _normalize_quaternion(child.orientation_xyzw)
    if parent_q is None or child_q is None:
        raise ValueError("cannot compose a pose with an invalid quaternion")
    rotated = _quaternion_rotate(parent_q, child.position)
    return Pose(
        position=tuple(
            parent.position[index] + rotated[index] for index in range(3)
        ),
        orientation_xyzw=_quaternion_multiply(parent_q, child_q),
    )


def _quaternion_rotate(
    quaternion: Sequence[float], vector: Sequence[float]
) -> tuple[float, float, float]:
    rotated = _quaternion_multiply(
        _quaternion_multiply(quaternion, (*vector, 0.0)),
        _quaternion_conjugate(quaternion),
    )
    return rotated[:3]


def _quaternion_to_rotvec(
    quaternion: Sequence[float],
) -> tuple[float, float, float]:
    normalized = _normalize_quaternion(quaternion)
    if normalized is None:
        return (0.0, 0.0, 0.0)
    x, y, z, w = normalized
    if w < 0.0:
        x, y, z, w = -x, -y, -z, -w
    vector_norm = math.sqrt(x * x + y * y + z * z)
    if vector_norm < 1e-9:
        return (0.0, 0.0, 0.0)
    angle = 2.0 * math.atan2(vector_norm, max(0.0, w))
    scale = angle / vector_norm
    return (x * scale, y * scale, z * scale)


def _rotvec_to_quaternion(
    rotvec: Sequence[float],
) -> tuple[float, float, float, float]:
    angle = math.sqrt(sum(float(component) ** 2 for component in rotvec))
    if angle < 1e-9:
        return (0.0, 0.0, 0.0, 1.0)
    scale = math.sin(angle * 0.5) / angle
    return (
        float(rotvec[0]) * scale,
        float(rotvec[1]) * scale,
        float(rotvec[2]) * scale,
        math.cos(angle * 0.5),
    )


def _quaternion_slerp(
    start: Sequence[float], end: Sequence[float], fraction: float
) -> tuple[float, float, float, float]:
    left = _normalize_quaternion(start)
    right = _normalize_quaternion(end)
    assert left is not None and right is not None
    dot = sum(a * b for a, b in zip(left, right))
    if dot < 0.0:
        right = tuple(-component for component in right)
        dot = -dot
    if dot > 0.9995:
        blended = tuple(
            a + fraction * (b - a) for a, b in zip(left, right)
        )
        normalized = _normalize_quaternion(blended)
        assert normalized is not None
        return normalized
    angle = math.acos(max(-1.0, min(1.0, dot)))
    denominator = math.sin(angle)
    start_scale = math.sin((1.0 - fraction) * angle) / denominator
    end_scale = math.sin(fraction * angle) / denominator
    return tuple(
        start_scale * a + end_scale * b for a, b in zip(left, right)
    )  # type: ignore[return-value]


def quaternion_delta_rotvec(
    previous_xyzw: Sequence[float], current_xyzw: Sequence[float]
) -> tuple[float, float, float] | None:
    """Return the shortest rotation expressed in the reference-local frame."""
    previous = _normalize_quaternion(previous_xyzw)
    current = _normalize_quaternion(current_xyzw)
    if previous is None or current is None:
        return None
    relative = _quaternion_multiply(_quaternion_conjugate(previous), current)
    return _quaternion_to_rotvec(relative)


def _proper_rotation_matrix(
    value: Sequence[float], name: str
) -> tuple[float, ...]:
    if len(value) != 9 or not _finite(value):
        raise ValueError(f"{name} must contain 9 finite values")
    matrix = tuple(float(component) for component in value)
    for row in range(3):
        for column in range(3):
            dot = sum(
                matrix[index * 3 + row] * matrix[index * 3 + column]
                for index in range(3)
            )
            expected = 1.0 if row == column else 0.0
            if abs(dot - expected) > 1e-5:
                raise ValueError(f"{name} must be orthonormal")
    determinant = (
        matrix[0] * (matrix[4] * matrix[8] - matrix[5] * matrix[7])
        - matrix[1] * (matrix[3] * matrix[8] - matrix[5] * matrix[6])
        + matrix[2] * (matrix[3] * matrix[7] - matrix[4] * matrix[6])
    )
    if abs(determinant - 1.0) > 1e-5:
        raise ValueError(f"{name} must have determinant +1")
    return matrix


def _transform(
    matrix: Sequence[float], vector: Sequence[float]
) -> tuple[float, float, float]:
    return tuple(
        sum(matrix[row * 3 + column] * vector[column] for column in range(3))
        for row in range(3)
    )  # type: ignore[return-value]


def _limit_norm(vector: Sequence[float], maximum: float) -> tuple[float, float, float]:
    norm = math.sqrt(sum(component * component for component in vector))
    if maximum > 0.0 and norm > maximum:
        scale = maximum / norm
        return tuple(component * scale for component in vector)  # type: ignore[return-value]
    return tuple(vector)  # type: ignore[return-value]


def _continuous_deadband(
    vector: Sequence[float], threshold: float
) -> tuple[float, float, float]:
    """Remove a radial deadband without a jump at its boundary."""

    value = tuple(float(component) for component in vector)
    norm = math.sqrt(sum(component * component for component in value))
    if threshold <= 0.0:
        return value  # type: ignore[return-value]
    if norm <= threshold or norm < 1e-12:
        return (0.0, 0.0, 0.0)
    scale = (norm - threshold) / norm
    return tuple(component * scale for component in value)  # type: ignore[return-value]


class QuestMotionMapper:
    """Map controller-local clutch motion into an EEF-local rigid transform."""

    def __init__(
        self,
        *,
        controller_to_eef_rotation: Sequence[float] = (
            1, 0, 0,
            0, 1, 0,
            0, 0, 1,
        ),
        translation_scale: float = 1.0,
        rotation_scale: float = 1.0,
        max_linear_offset_m: float = 0.5,
        max_angular_offset_rad: float = math.pi,
        linear_deadband_m: float = 0.0005,
        angular_deadband_rad: float = 0.005,
        output_frame: str = "ee_local",
        world_axis_rotation: Sequence[float] = (
            1, 0, 0,
            0, 1, 0,
            0, 0, 1,
        ),
    ) -> None:
        self._controller_to_eef = _proper_rotation_matrix(
            controller_to_eef_rotation, "controller_to_eef_rotation"
        )
        self._world_axis_rotation = _proper_rotation_matrix(
            world_axis_rotation, "world_axis_rotation"
        )
        self._translation_scale = float(translation_scale)
        self._rotation_scale = float(rotation_scale)
        self._max_linear = float(max_linear_offset_m)
        self._max_angular = float(max_angular_offset_rad)
        self._linear_deadband = float(linear_deadband_m)
        self._angular_deadband = float(angular_deadband_rad)
        if output_frame not in {"ee_local", "world"}:
            raise ValueError("output_frame must be 'ee_local' or 'world'")
        self.output_frame = output_frame
        self._active = False
        self._release_required = False
        self._reference_pose: Pose | None = None

    @property
    def active(self) -> bool:
        return self._active

    def set_active(self, active: bool) -> bool:
        active = bool(active)
        if not active:
            self._release_required = False
        elif self._release_required:
            return False
        changed = active != self._active
        if changed:
            self._active = active
            self._reference_pose = None
        return changed

    def fault_stop(self) -> None:
        self._active = False
        self._release_required = True
        self._reference_pose = None

    def update_pose(self, pose: Pose) -> PoseOffset | None:
        orientation = _normalize_quaternion(pose.orientation_xyzw)
        if not self._active or not _finite(pose.position) or orientation is None:
            return None

        reference = self._reference_pose
        if reference is None:
            self._reference_pose = Pose(pose.position, orientation)
            return PoseOffset((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))

        reference_orientation = _normalize_quaternion(reference.orientation_xyzw)
        assert reference_orientation is not None
        local_rotation = quaternion_delta_rotvec(
            reference_orientation, orientation
        )
        if local_rotation is None:
            return None
        world_translation = tuple(
            pose.position[index] - reference.position[index] for index in range(3)
        )
        if self.output_frame == "world":
            source_translation = world_translation
            relative_q = _quaternion_multiply(
                orientation, _quaternion_conjugate(reference_orientation)
            )
            source_rotation = _quaternion_to_rotvec(relative_q)
            canonical_mapping = self._world_axis_rotation
        else:
            source_translation = _quaternion_rotate(
                _quaternion_conjugate(reference_orientation), world_translation
            )
            source_rotation = local_rotation
            canonical_mapping = self._controller_to_eef

        translation = tuple(
            component * self._translation_scale
            for component in _transform(
                canonical_mapping, source_translation
            )
        )
        rotation = tuple(
            component * self._rotation_scale
            for component in _transform(
                canonical_mapping, source_rotation
            )
        )
        control_rotation = tuple(
            component * self._rotation_scale
            for component in _transform(
                self._controller_to_eef, local_rotation
            )
        )
        translation = _continuous_deadband(translation, self._linear_deadband)
        rotation = _continuous_deadband(rotation, self._angular_deadband)
        control_rotation = _continuous_deadband(
            control_rotation, self._angular_deadband
        )
        return PoseOffset(
            _limit_norm(translation, self._max_linear),
            _limit_norm(rotation, self._max_angular),
            _limit_norm(control_rotation, self._max_angular),
        )


class PoseOffsetInterpolator:
    """Fixed-delay translation lerp and rotation SLERP for bursty samples."""

    def __init__(
        self,
        delay_sec: float = 0.025,
        smoothing_time_constant_sec: float = 0.0,
    ) -> None:
        if delay_sec < 0.0:
            raise ValueError("delay_sec must be >= 0")
        if smoothing_time_constant_sec < 0.0:
            raise ValueError("smoothing_time_constant_sec must be >= 0")
        self._delay_sec = float(delay_sec)
        self._smoothing_time_constant_sec = float(
            smoothing_time_constant_sec
        )
        self._samples: list[tuple[float, PoseOffset]] = []
        self._last_output: PoseOffset | None = None
        self._last_output_at: float | None = None

    def reset(self) -> None:
        self._samples.clear()
        self._last_output = None
        self._last_output_at = None

    def add(self, timestamp: float, offset: PoseOffset) -> None:
        if not math.isfinite(timestamp) or not _finite(offset.as_list()):
            return
        sample = (float(timestamp), offset)
        if self._samples and timestamp < self._samples[-1][0]:
            return
        if self._samples and timestamp == self._samples[-1][0]:
            self._samples[-1] = sample
        else:
            self._samples.append(sample)
        if len(self._samples) > 120:
            del self._samples[:-120]

    def sample(self, now: float) -> PoseOffset | None:
        if not self._samples or not math.isfinite(now):
            return None
        target_time = float(now) - self._delay_sec
        while len(self._samples) > 2 and self._samples[1][0] <= target_time:
            self._samples.pop(0)
        if len(self._samples) == 1 or target_time <= self._samples[0][0]:
            raw = self._samples[0][1]
        elif target_time >= self._samples[-1][0]:
            raw = self._samples[-1][1]
        else:
            left_time, left = self._samples[0]
            right_time, right = self._samples[1]
            fraction = (target_time - left_time) / (right_time - left_time)
            raw = self._blend(left, right, fraction)
        return self._smooth(float(now), raw)

    @staticmethod
    def _blend(left: PoseOffset, right: PoseOffset, fraction: float) -> PoseOffset:
        translation = tuple(
            start + fraction * (end - start)
            for start, end in zip(left.translation, right.translation)
        )
        rotation_q = _quaternion_slerp(
            _rotvec_to_quaternion(left.rotation_rotvec),
            _rotvec_to_quaternion(right.rotation_rotvec),
            fraction,
        )
        left_control = left.control_rotation_rotvec or left.rotation_rotvec
        right_control = right.control_rotation_rotvec or right.rotation_rotvec
        control_q = _quaternion_slerp(
            _rotvec_to_quaternion(left_control),
            _rotvec_to_quaternion(right_control),
            fraction,
        )
        return PoseOffset(
            translation,
            _quaternion_to_rotvec(rotation_q),
            _quaternion_to_rotvec(control_q),
        )

    def _smooth(self, now: float, raw: PoseOffset) -> PoseOffset:
        previous = self._last_output
        previous_at = self._last_output_at
        tau = self._smoothing_time_constant_sec
        if previous is None or previous_at is None or tau <= 0.0 or now <= previous_at:
            result = raw
        else:
            alpha = 1.0 - math.exp(-(now - previous_at) / tau)
            result = self._blend(previous, raw, alpha)
        self._last_output = result
        self._last_output_at = now
        return result


class HoldActionLatch:
    """Emit once after a button is held continuously while allowed."""

    def __init__(self, hold_sec: float) -> None:
        if hold_sec < 0.0:
            raise ValueError("hold_sec must be >= 0")
        self._hold_sec = float(hold_sec)
        self._pressed_at: float | None = None
        self._fired = False

    def update(self, *, pressed: bool, allowed: bool, now: float) -> bool:
        if not allowed or not pressed or not math.isfinite(now):
            self._pressed_at = None
            self._fired = False
            return False
        if self._pressed_at is None:
            self._pressed_at = float(now)
            return self._hold_sec == 0.0 and self._fire()
        if not self._fired and now - self._pressed_at >= self._hold_sec:
            return self._fire()
        return False

    def _fire(self) -> bool:
        self._fired = True
        return True
