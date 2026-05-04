import pytest

from mimicrec.inference.contract import ContractSpec


YAML_OK = """
name: gemma_test
description: "test"
endpoint:
  url: "http://localhost:8001/predict"
  method: POST
  timeout_s: 5.0
  retry: { max_attempts: 0 }
request:
  images:
    front: { field: image_primary, encoding: jpeg_base64, resize: [224, 224], jpeg_quality: 90 }
  state:
    field: proprio
    components: [joint_pos, gripper_pos]
    normalization: { method: none }
  instruction:
    field: instruction
response:
  actions_path: actions
  chunk: { expected_size: 16, on_size_mismatch: use_actual }
  action:
    type: ee_delta
    frame: ee_local
    pose: { units: meter_axisangle_rad }
    gripper: { kind: absolute, units: normalized_0_1 }
    components: [ee_delta, gripper]
    normalization:
      method: mean_std
      stats_ref: { type: vla_export, dataset: SO101 }
loop:
  prefetch_threshold: 0.5
  max_inflight: 1
"""


def test_loads_minimal_yaml():
    spec = ContractSpec.from_yaml_text(YAML_OK)
    assert spec.name == "gemma_test"
    assert spec.endpoint.url.startswith("http://")
    assert spec.response.action.type == "ee_delta"
    assert spec.loop.max_inflight == 1


def test_endpoint_url_must_be_http():
    bad = YAML_OK.replace("http://localhost:8001/predict", "ftp://nope")
    with pytest.raises(ValueError, match="http"):
        ContractSpec.from_yaml_text(bad)
