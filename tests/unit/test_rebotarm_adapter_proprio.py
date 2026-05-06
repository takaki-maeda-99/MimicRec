from mimicrec.adapters.rebotarm_zmq import ReBotArmZmqAdapter
from mimicrec.adapters.types import GripperConvention, ProprioLayout


def test_rebot_default_gripper_convention():
    c = ReBotArmZmqAdapter.default_gripper_convention()
    assert isinstance(c, GripperConvention)
    # Inferred from configs/mapper/so_to_rebotarm_ee.yaml:
    # gripper_invert=true + out_min/max=0/1 → 1=closed, 0=open
    assert c.closed_at == 1.0
    assert c.open_at == 0.0


def test_rebot_proprio_layout():
    layout = ReBotArmZmqAdapter.proprio_layout()
    assert isinstance(layout, ProprioLayout)
    assert layout.columns == (
        "observation.state.joint_pos",
        "observation.state.gripper_pos",
    )
    # NOTE: 'join3' (no 't') intentional — reBotArm URDF spells it as 'join3'.
    assert layout.output_names == (
        "joint1", "joint2", "join3", "joint4", "joint5", "joint6", "gripper",
    )
    assert layout.gripper_via_column == "observation.state.gripper_pos"
    assert layout.gripper_index_in_column == 0
