"""Snapshot tests for configs/inference/rebotarm_v47.yaml.

Pair on the X-VLA-Adapter side: a deploy YAML that loads HF ckpt
takaki99/x-vla-adapter-v47-arch-v3-step95000 with request_fields matching
{image_primary, image_wrist, proprio, instruction} and proprio.adapt that
pads MimicRec's 7-float ee_pose+gripper proprio to the model's 8-dim. Pin
the MimicRec-side fields here so an unintentional edit breaks a clear
test rather than producing silent runtime errors against the server.
"""
from pathlib import Path

from mimicrec.inference.contract import ContractSpec


REPO_ROOT = Path(__file__).resolve().parents[2]
REBOTARM_V47 = REPO_ROOT / "configs" / "inference" / "rebotarm_v47.yaml"


def test_rebotarm_v47_loads_and_pins_critical_fields():
    spec = ContractSpec.from_yaml_text(REBOTARM_V47.read_text())
    assert spec.name == "rebotarm_v47"
    assert spec.endpoint.url == "http://localhost:8001/predict"
    assert spec.endpoint.method == "POST"
    assert spec.endpoint.retry.max_attempts == 0

    assert spec.request.state.components == ["ee_pos", "ee_rotvec", "gripper_pos"]
    assert spec.request.state.normalization.method == "none"
    assert set(spec.request.images.keys()) == {"front", "wrist"}
    assert spec.request.images["front"].field == "image_primary"
    assert spec.request.images["wrist"].field == "image_wrist"

    assert spec.response.action.frame == "world"
    assert spec.response.action.type == "ee_delta"
    assert spec.response.action.normalization.method == "none"
    assert spec.response.action.components == ["ee_delta", "gripper"]
    assert spec.response.chunk.expected_size == 8
    assert spec.response.chunk.on_size_mismatch == "reject"
