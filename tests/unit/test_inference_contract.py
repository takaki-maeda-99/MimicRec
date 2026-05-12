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


import os
import yaml as _yaml


def _yaml_with_overrides(**overrides) -> str:
    """Build a YAML test fixture by mutating a parsed dict — much less
    fragile than running multiple `replace()` calls on a string.

    `overrides` keys can be:
      - `headers`: dict to set on `endpoint.headers`
      - `image_field_dup`: bool — make both image fields collide
      - `done`: dict for `response.done`
      - `pose_units`: str for `response.action.pose.units`
      - `normalization_method`: str for `response.action.normalization.method`
    """
    d = _yaml.safe_load(YAML_OK)
    if "headers" in overrides:
        d["endpoint"]["headers"] = overrides["headers"]
    if overrides.get("image_field_dup"):
        d["request"]["images"] = {
            "front": {"field": "SAME", "encoding": "jpeg_base64",
                      "resize": [224, 224], "jpeg_quality": 90},
            "wrist": {"field": "SAME", "encoding": "jpeg_base64",
                      "resize": [224, 224], "jpeg_quality": 90},
        }
    if "done" in overrides:
        d["response"]["done"] = overrides["done"]
    if "pose_units" in overrides:
        d["response"]["action"]["pose"]["units"] = overrides["pose_units"]
    if "normalization_method" in overrides:
        d["response"]["action"]["normalization"] = {"method": overrides["normalization_method"]}
    return _yaml.safe_dump(d)


def test_env_var_interpolation(monkeypatch):
    monkeypatch.setenv("VLA_API_TOKEN", "secret123")
    text = _yaml_with_overrides(headers={"Authorization": "Bearer ${VLA_API_TOKEN}"})
    spec = ContractSpec.from_yaml_text(text)
    assert spec.endpoint.headers["Authorization"] == "Bearer secret123"


def test_missing_env_var_fails(monkeypatch):
    monkeypatch.delenv("VLA_API_TOKEN", raising=False)
    text = _yaml_with_overrides(headers={"Authorization": "Bearer ${VLA_API_TOKEN}"})
    with pytest.raises(ValueError, match="VLA_API_TOKEN"):
        ContractSpec.from_yaml_text(text)


def test_image_fields_must_be_unique():
    text = _yaml_with_overrides(image_field_dup=True)
    with pytest.raises(ValueError, match="unique"):
        ContractSpec.from_yaml_text(text)


def test_done_scope_step_rejected():
    text = _yaml_with_overrides(done={
        "path": "done", "type": "bool", "scope": "step", "action_on_done": "auto_stop",
    })
    with pytest.raises(ValueError, match="done.scope"):
        ContractSpec.from_yaml_text(text)


def test_pose_units_mm_euler_deg_rejected_in_mvp():
    """MVP only implements meter_axisangle_rad; mm_euler_deg must fail at load
    so a config swap can't silently mis-scale by 1000x or mis-interpret rotation."""
    text = _yaml_with_overrides(pose_units="mm_euler_deg")
    with pytest.raises(ValueError, match="pose.units"):
        ContractSpec.from_yaml_text(text)


import json


COMPONENTS_DIM = {
    "joint_pos": "Narm",      # robot-config-dependent
    "gripper_pos": 1,
    "ee_delta": 6,
    "gripper": 1,
}


def test_stats_path_resolution_vla_export(tmp_path, monkeypatch):
    # set up a fake VLA export tree
    monkeypatch.setenv("MIMICREC_VLA_DEST_ROOT", str(tmp_path))
    (tmp_path / "SO101" / "meta").mkdir(parents=True)
    stats_file = tmp_path / "SO101" / "meta" / "action_stats.json"
    stats_file.write_text(json.dumps({"mean": [0.0]*7, "std": [1.0]*7}))

    spec = ContractSpec.from_yaml_text(YAML_OK)
    resolved = spec.resolve_action_stats()
    assert resolved == {"mean": [0.0]*7, "std": [1.0]*7}


def test_stats_path_missing_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("MIMICREC_VLA_DEST_ROOT", str(tmp_path))
    spec = ContractSpec.from_yaml_text(YAML_OK)
    with pytest.raises(FileNotFoundError, match="action_stats.json"):
        spec.resolve_action_stats()


def test_stats_length_mismatch_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("MIMICREC_VLA_DEST_ROOT", str(tmp_path))
    (tmp_path / "SO101" / "meta").mkdir(parents=True)
    stats_file = tmp_path / "SO101" / "meta" / "action_stats.json"
    stats_file.write_text(json.dumps({"mean": [0.0]*5, "std": [1.0]*5}))  # wrong length

    spec = ContractSpec.from_yaml_text(YAML_OK)
    with pytest.raises(ValueError, match="length"):
        spec.resolve_action_stats()


def test_resolve_returns_none_when_method_is_none():
    """method=none → no stats needed; lifecycle can call unconditionally."""
    spec = ContractSpec.from_yaml_text(_yaml_with_overrides(normalization_method="none"))
    assert spec.resolve_action_stats() is None


def test_component_registry_includes_ee_pose():
    from mimicrec.inference.contract import _COMPONENT_DIM, _expected_dim
    assert _COMPONENT_DIM["ee_pos"] == 3
    assert _COMPONENT_DIM["ee_rotvec"] == 3
    assert _expected_dim(["ee_pos", "ee_rotvec", "gripper_pos"]) == 7


def test_contract_loads_with_ee_pose_components():
    yaml_with_ee = YAML_OK.replace(
        "components: [joint_pos, gripper_pos]",
        "components: [ee_pos, ee_rotvec, gripper_pos]",
    )
    spec = ContractSpec.from_yaml_text(yaml_with_ee)
    assert spec.request.state.components == ["ee_pos", "ee_rotvec", "gripper_pos"]
