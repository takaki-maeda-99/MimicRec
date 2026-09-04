import numpy as np
import pytest

from mimicrec.inference.contract import ContractSpec
from mimicrec.inference.motion_decoder import MotionActionDecoder


def _contract(*, units="se3_log_increment", gripper_kind="absolute"):
    return ContractSpec.model_validate({
        "name": "motion",
        "motion_group": "left_hand",
        "endpoint": {"url": "http://localhost:8001/predict"},
        "request": {
            "images": {},
            "state": {"field": "state", "components": ["ee_pos", "ee_rotvec"]},
            "instruction": {"field": "instruction"},
        },
        "response": {
            "actions_path": "actions",
            "chunk": {"expected_size": 1, "on_size_mismatch": "reject"},
            "action": {
                "type": "ee_delta",
                "frame": "ee_local",
                "pose": {"units": units},
                "gripper": {"kind": gripper_kind, "units": "normalized_0_1"},
                "components": ["ee_delta", "gripper"],
            },
        },
    })


def test_motion_decoder_preserves_native_se3_log_token():
    decoder = MotionActionDecoder(_contract(), duration_sec=0.02)

    steps = decoder.decode({"actions": [[0.01, 0, 0, 0, 0, 0.02, 0.7]]})

    assert steps[0].delta.tangent == pytest.approx([0.01, 0, 0, 0, 0, 0.02])
    assert steps[0].delta.duration_sec == pytest.approx(0.02)
    assert steps[0].auxiliary["gripper"] == pytest.approx(0.7)


def test_legacy_translation_rotvec_output_is_converted_through_se3_log():
    decoder = MotionActionDecoder(
        _contract(units="meter_axisangle_rad"), duration_sec=0.02
    )

    step = decoder.decode({
        "actions": [[0.1, 0, 0, 0, 0, np.pi / 2, 0]]
    })[0]

    # With simultaneous rotation, the se(3) logarithm's rho differs from the
    # literal transform translation column.
    assert not np.allclose(step.delta.tangent[:3], [0.1, 0, 0])
    assert step.delta.as_transform()[:3, 3] == pytest.approx([0.1, 0, 0])


def test_delta_gripper_accumulates_and_clamps():
    decoder = MotionActionDecoder(
        _contract(gripper_kind="delta"), duration_sec=0.02
    )

    first = decoder.decode({"actions": [[0, 0, 0, 0, 0, 0, 0.8]]})[0]
    second = decoder.decode({"actions": [[0, 0, 0, 0, 0, 0, 0.8]]})[0]

    assert first.auxiliary["gripper"] == pytest.approx(0.8)
    assert second.auxiliary["gripper"] == pytest.approx(1.0)
