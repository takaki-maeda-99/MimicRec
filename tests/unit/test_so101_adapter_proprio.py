from mimicrec.adapters.so101 import SO101Adapter
from mimicrec.adapters.types import GripperConvention, ProprioLayout


def test_so101_default_gripper_convention():
    c = SO101Adapter.default_gripper_convention()
    assert isinstance(c, GripperConvention)
    assert c.closed_at == 0.0
    assert c.open_at == 100.0


def test_so101_proprio_layout():
    layout = SO101Adapter.proprio_layout()
    assert isinstance(layout, ProprioLayout)
    assert layout.columns == ("observation.state.joint_pos",)
    assert layout.output_names == (
        "shoulder_pan", "shoulder_lift", "elbow_flex",
        "wrist_flex", "wrist_roll", "gripper",
    )
    assert layout.gripper_via_column == "observation.state.joint_pos"
    assert layout.gripper_index_in_column == 5
