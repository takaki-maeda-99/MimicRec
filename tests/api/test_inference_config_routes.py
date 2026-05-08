"""Tests for /api/configs/inference list/get endpoints.

These pin the regression that motivated the recent fix:
- list returns `{items: [...]}` (not bare list) so frontend `r.items` works.
- list `name` is the file stem (matches the get endpoint's lookup key).
- one broken YAML must NOT 500 the whole list — surface as `error` field.
"""
from __future__ import annotations
import textwrap
from pathlib import Path

from httpx import AsyncClient, ASGITransport
from mimicrec.api.app import create_app


_GOOD = textwrap.dedent("""
    name: my_pretty_title
    description: "Smoke contract."
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
      chunk:
        expected_size: 8
        on_size_mismatch: use_actual
      action:
        type: ee_delta
        frame: ee_local
        pose:
          units: meter_axisangle_rad
        gripper:
          kind: absolute
          units: normalized_0_1
        components: [ee_delta, gripper]
        normalization: { method: none }
""").strip()


_BROKEN_ENV = textwrap.dedent("""
    name: needs_secret
    description: "References a missing env var."
    endpoint:
      url: "http://localhost:8001/predict"
      headers:
        Authorization: "Bearer ${THIS_VAR_IS_NOT_SET_XYZ}"
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
      chunk:
        expected_size: 8
        on_size_mismatch: use_actual
      action:
        type: ee_delta
        frame: ee_local
        pose:
          units: meter_axisangle_rad
        gripper:
          kind: absolute
          units: normalized_0_1
        components: [ee_delta, gripper]
        normalization: { method: none }
""").strip()


def _build_configs_root(tmp_path: Path, files: dict[str, str]) -> Path:
    inference_dir = tmp_path / "inference"
    inference_dir.mkdir(parents=True)
    for name, body in files.items():
        (inference_dir / name).write_text(body)
    return tmp_path


async def _list(app) -> dict:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/configs/inference")
    assert r.status_code == 200, r.text
    return r.json()


async def test_list_inference_configs_wraps_in_items(tmp_path):
    configs_root = _build_configs_root(tmp_path, {"good_one.yaml": _GOOD})
    app = create_app()
    app.state.configs_root = configs_root
    body = await _list(app)
    # Frontend expects `r.items`. Wrapping in {items: [...]} is the contract.
    assert isinstance(body, dict)
    assert "items" in body
    assert isinstance(body["items"], list)
    assert len(body["items"]) == 1


async def test_list_uses_file_stem_as_name_and_spec_name_as_title(tmp_path):
    configs_root = _build_configs_root(tmp_path, {"good_one.yaml": _GOOD})
    app = create_app()
    app.state.configs_root = configs_root
    body = await _list(app)
    item = body["items"][0]
    assert item["name"] == "good_one"           # file stem (= get endpoint id)
    assert item["title"] == "my_pretty_title"   # YAML's spec.name → display
    assert item["description"] == "Smoke contract."
    assert "error" not in item


async def test_list_is_robust_to_broken_yaml(tmp_path):
    configs_root = _build_configs_root(
        tmp_path,
        {"good_one.yaml": _GOOD, "broken.yaml": _BROKEN_ENV},
    )
    app = create_app()
    app.state.configs_root = configs_root
    body = await _list(app)
    items = {it["name"]: it for it in body["items"]}
    # The broken yaml must NOT poison the list; both entries are present.
    assert set(items.keys()) == {"good_one", "broken"}
    # The good one parses cleanly; no `error` key.
    assert "error" not in items["good_one"]
    # The broken one is surfaced with an error string and a load-failure
    # description — the UI uses these to disable the dropdown option and
    # explain why.
    assert "error" in items["broken"]
    assert "THIS_VAR_IS_NOT_SET_XYZ" in items["broken"]["error"]
    assert items["broken"]["description"].startswith("⚠ failed to load")


async def test_get_inference_config_resolves_by_file_stem(tmp_path):
    configs_root = _build_configs_root(tmp_path, {"good_one.yaml": _GOOD})
    app = create_app()
    app.state.configs_root = configs_root
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Loader looks up by file stem; list returned `name=good_one`, so this
        # round-trip must succeed even though the YAML's spec.name differs.
        r = await ac.get("/api/configs/inference/good_one")
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "my_pretty_title"


async def test_list_inference_returns_empty_when_directory_missing(tmp_path):
    # No inference/ subdir at all.
    app = create_app()
    app.state.configs_root = tmp_path
    body = await _list(app)
    assert body == {"items": []}
