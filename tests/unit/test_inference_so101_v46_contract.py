"""Snapshot tests for configs/inference/so101_v46.yaml.

The pair on the X-VLA-Adapter side is
~/X-VLA-Adapter/configs/deploy/so101_v46.yaml. Cross-repo drift is the
operator's responsibility; this test pins the MimicRec-side fields so an
unintentional edit breaks a clear test rather than producing silent
runtime errors against the server."""
from pathlib import Path

from mimicrec.inference.contract import ContractSpec


REPO_ROOT = Path(__file__).resolve().parents[2]
SO101_V46 = REPO_ROOT / "configs" / "inference" / "so101_v46.yaml"


def test_so101_v46_loads_and_pins_critical_fields():
    spec = ContractSpec.from_yaml_text(SO101_V46.read_text())
    assert spec.name == "so101_v46"
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
