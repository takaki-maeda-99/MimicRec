import pytest

from mimicrec.adapters.types import GripperConvention, ProprioLayout
from mimicrec.datasets.exporters.info_json import to_vla_info, ACTION_NAMES


def _so101_layout() -> ProprioLayout:
    return ProprioLayout(
        columns=("observation.state.joint_pos",),
        output_names=("shoulder_pan", "shoulder_lift", "elbow_flex",
                      "wrist_flex", "wrist_roll", "gripper"),
        gripper_via_column="observation.state.joint_pos",
        gripper_index_in_column=5,
    )


def _rebot_layout() -> ProprioLayout:
    return ProprioLayout(
        columns=("observation.state.joint_pos", "observation.state.gripper_pos"),
        output_names=("joint1", "joint2", "join3", "joint4", "joint5", "joint6", "gripper"),
        gripper_via_column="observation.state.gripper_pos",
        gripper_index_in_column=0,
    )


def test_action_names_are_ee_delta_components():
    assert ACTION_NAMES == ["ee_dx", "ee_dy", "ee_dz",
                            "ee_drx", "ee_dry", "ee_drz", "gripper"]


def test_to_vla_info_writes_action_feature_with_ee_delta_names():
    out = to_vla_info(
        {}, robot_type="SO101Adapter",
        gripper_convention={"closed_at": 0.0, "open_at": 100.0},
        proprio_layout=_so101_layout(), n_proprio=6,
    )
    assert out["features"]["action"] == {
        "dtype": "float32", "shape": [7], "names": ACTION_NAMES,
    }


def test_to_vla_info_observation_state_so101_shape_and_names():
    out = to_vla_info(
        {}, robot_type="SO101Adapter",
        gripper_convention={"closed_at": 0.0, "open_at": 100.0},
        proprio_layout=_so101_layout(), n_proprio=6,
    )
    assert out["features"]["observation.state"] == {
        "dtype": "float32",
        "shape": [6],
        "names": list(_so101_layout().output_names),
    }


def test_to_vla_info_observation_state_rebot_shape_and_names():
    out = to_vla_info(
        {}, robot_type="ReBotArmZmqAdapter",
        gripper_convention={"closed_at": 1.0, "open_at": 0.0},
        proprio_layout=_rebot_layout(), n_proprio=7,
    )
    assert out["features"]["observation.state"] == {
        "dtype": "float32",
        "shape": [7],
        "names": list(_rebot_layout().output_names),
    }


def test_to_vla_info_carries_robot_type_gripper_convention_proprio_layout():
    out = to_vla_info(
        {}, robot_type="SO101Adapter",
        gripper_convention={"closed_at": 0.0, "open_at": 100.0},
        proprio_layout=_so101_layout(), n_proprio=6,
    )
    assert out["robot_type"] == "SO101Adapter"
    assert out["gripper_convention"] == {"closed_at": 0.0, "open_at": 100.0}
    assert out["proprio_layout"] == {
        "columns": list(_so101_layout().columns),
        "output_names": list(_so101_layout().output_names),
        "gripper_via_column": "observation.state.joint_pos",
        "gripper_index_in_column": 5,
    }


def test_to_vla_info_raises_when_name_count_mismatches_n_proprio():
    with pytest.raises(ValueError, match="proprio name/shape mismatch"):
        to_vla_info(
            {}, robot_type="SO101Adapter",
            gripper_convention={"closed_at": 0.0, "open_at": 100.0},
            proprio_layout=_so101_layout(),    # 6 names
            n_proprio=7,                        # disagree
        )


def test_to_vla_info_does_not_mutate_input():
    src = {"features": {"existing": {"dtype": "string"}}}
    to_vla_info(
        src, robot_type="SO101Adapter",
        gripper_convention={"closed_at": 0.0, "open_at": 100.0},
        proprio_layout=_so101_layout(), n_proprio=6,
    )
    assert src == {"features": {"existing": {"dtype": "string"}}}
