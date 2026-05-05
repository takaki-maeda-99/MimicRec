import pytest

from mimicrec.adapters.types import GripperConvention, ProprioLayout


def test_gripper_convention_zero_span_raises():
    with pytest.raises(ValueError, match="zero span"):
        GripperConvention(closed_at=42.0, open_at=42.0)


def test_gripper_convention_normal_span_ok():
    c = GripperConvention(closed_at=0.0, open_at=100.0)
    assert c.closed_at == 0.0 and c.open_at == 100.0


def test_gripper_convention_inverted_span_ok():
    # reBot has closed_at > open_at — must be allowed.
    c = GripperConvention(closed_at=1.0, open_at=0.0)
    assert c.closed_at == 1.0 and c.open_at == 0.0


def test_proprio_layout_gripper_via_column_must_be_in_columns():
    with pytest.raises(ValueError, match="not in columns"):
        ProprioLayout(
            columns=("observation.state.joint_pos",),
            output_names=("a", "b"),
            gripper_via_column="observation.state.gripper_pos",
            gripper_index_in_column=0,
        )


def test_proprio_layout_gripper_index_must_be_non_negative():
    with pytest.raises(ValueError, match="must be >= 0"):
        ProprioLayout(
            columns=("observation.state.joint_pos",),
            output_names=("a",),
            gripper_via_column="observation.state.joint_pos",
            gripper_index_in_column=-1,
        )


def test_proprio_layout_minimal_valid():
    p = ProprioLayout(
        columns=("observation.state.joint_pos",),
        output_names=("shoulder_pan",),
        gripper_via_column="observation.state.joint_pos",
        gripper_index_in_column=0,
    )
    assert p.columns == ("observation.state.joint_pos",)
