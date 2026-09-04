import numpy as np
import pytest

from mimicrec.motion.se3 import (
    SE3Delta,
    SE3Frame,
    compose_deltas,
    se3_exp,
    se3_log,
)


def test_se3_exp_log_round_trip_with_coupled_translation_rotation():
    tangent = np.array([0.12, -0.04, 0.08, 0.3, -0.2, 0.1])

    transform = se3_exp(tangent)

    assert se3_log(transform) == pytest.approx(tangent, abs=1e-9)
    assert not np.allclose(transform[:3, 3], tangent[:3])


def test_delta_velocity_conversion_uses_duration_not_implicit_hz():
    velocity = np.array([0.6, 0, 0, 0, 0, 1.2])

    delta = SE3Delta.from_velocity(velocity, duration_sec=1 / 60)

    assert delta.tangent == pytest.approx(velocity / 60)
    assert delta.as_velocity() == pytest.approx(velocity)


def test_masked_axes_are_zeroed_and_arrays_are_immutable():
    delta = SE3Delta(
        np.ones(6),
        active_mask=np.array([1, 1, 0, 0, 0, 1], dtype=bool),
    )

    assert delta.tangent == pytest.approx([1, 1, 0, 0, 0, 1])
    with pytest.raises(ValueError):
        delta.tangent[0] = 2


def test_compose_deltas_multiplies_transforms_in_order():
    first = SE3Delta(np.array([0, 0, 0, 0, 0, np.pi / 2]), duration_sec=0.1)
    second = SE3Delta(np.array([1, 0, 0, 0, 0, 0]), duration_sec=0.2)

    combined = compose_deltas([first, second])

    assert combined.duration_sec == pytest.approx(0.3)
    assert combined.frame == SE3Frame.EE_LOCAL
    assert combined.as_transform() == pytest.approx(
        first.as_transform() @ second.as_transform()
    )


def test_different_frames_cannot_be_composed_silently():
    with pytest.raises(ValueError, match="different frames"):
        compose_deltas([
            SE3Delta.identity(frame="ee_local"),
            SE3Delta.identity(frame="world"),
        ])
