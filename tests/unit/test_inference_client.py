import asyncio
import base64
import json

import numpy as np
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient

from mimicrec.adapters.so101 import SO101Adapter
from mimicrec.inference.client import InferenceClient
from mimicrec.inference.contract import ContractSpec
from mimicrec.types import Frame, RobotState, Stamped


YAML = """
name: test
endpoint:
  url: REPLACED_AT_TEST
  method: POST
  retry: { max_attempts: 0 }
request:
  images: { front: { field: image_primary, encoding: jpeg_base64, resize: [16,16], jpeg_quality: 90 } }
  state:  { field: proprio, components: [joint_pos, gripper_pos], normalization: { method: none } }
  instruction: { field: instruction }
response:
  actions_path: actions
  chunk: { expected_size: 2, on_size_mismatch: use_actual }
  action:
    type: ee_delta
    frame: ee_local
    pose: { units: meter_axisangle_rad }
    gripper: { kind: absolute, units: normalized_0_1 }
    components: [ee_delta, gripper]
    normalization: { method: none }
loop:
  prefetch_threshold: 0.5
  max_inflight: 1
"""


async def test_client_round_trip(aiohttp_client):
    received: list[dict] = []

    async def handler(request):
        body = await request.json()
        received.append(body)
        return web.json_response({"actions": [[0.0]*7, [0.1]*7]})

    app = web.Application()
    app.router.add_post("/predict", handler)
    server = await aiohttp_client(app)
    url = str(server.make_url("/predict"))

    spec = ContractSpec.from_yaml_text(YAML.replace("REPLACED_AT_TEST", url))
    client = InferenceClient(
        spec=spec,
        gripper_convention=SO101Adapter.default_gripper_convention(),
        proprio_layout=SO101Adapter.proprio_layout(),
    )
    img = np.zeros((16, 16, 3), dtype=np.uint8)
    frames = {"front": Stamped(value=Frame(image=img, t_mono_ns=1), t_mono_ns=1)}
    state = Stamped(value=RobotState(
        joint_pos=np.zeros(6), joint_vel=np.zeros(6),
        joint_effort=np.zeros(6), gripper_pos=0.0, t_mono_ns=2), t_mono_ns=2)
    instr = Stamped(value="pick", t_mono_ns=3)

    body = await client.predict(frames, state, instr, extras={"_t_mono_ns": {"x": 0}})

    assert "actions" in body
    assert len(received) == 1
    sent = received[0]
    assert sent["instruction"] == "pick"
    assert "image_primary" in sent
    # decode confirms it's a valid jpeg base64 of a 16x16 image
    raw = base64.b64decode(sent["image_primary"])
    assert raw.startswith(b"\xff\xd8")  # JPEG magic
    await client.aclose()


# ---------------------------------------------------------------------------
# EE-encode tests
# ---------------------------------------------------------------------------

from pathlib import Path
from scipy.spatial.transform import Rotation as R

from mimicrec.kinematics.fk import FKService, KinematicsConfig
from mimicrec.adapters.types import GripperConvention, ProprioLayout


_REPO_ROOT = Path(__file__).resolve().parents[2]
_FK_CFG = KinematicsConfig(
    urdf_path=str(_REPO_ROOT / "configs" / "urdf" / "so101" / "so101.urdf"),
    target_frame="gripper_frame_link",
    joint_names=["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"],
)

_EE_YAML = """
name: t
endpoint: { url: "http://x", method: POST, retry: { max_attempts: 0 } }
request:
  images: { front: { field: image_primary, encoding: jpeg_base64, resize: [16,16], jpeg_quality: 90 } }
  state:
    field: proprio
    components: [ee_pos, ee_rotvec, gripper_pos]
    normalization: { method: none }
  instruction: { field: instruction }
response:
  actions_path: actions
  chunk: { expected_size: 1, on_size_mismatch: use_actual }
  action:
    type: ee_delta
    frame: world
    pose: { units: meter_axisangle_rad }
    gripper: { kind: absolute, units: normalized_0_1 }
    components: [ee_delta, gripper]
    normalization: { method: none }
loop: { prefetch_threshold: 0.5, max_inflight: 1 }
"""


def _make_state(joint_pos, ee_pos=None, ee_rotvec=None, gripper_pos=None):
    n = joint_pos.shape[0]
    return RobotState(
        joint_pos=joint_pos.astype(np.float32),
        joint_vel=np.zeros(n, dtype=np.float32),
        joint_effort=np.zeros(n, dtype=np.float32),
        ee_pos=ee_pos, ee_rotvec=ee_rotvec, gripper_pos=gripper_pos,
    )


def _make_client_so101(**overrides):
    spec = overrides.pop("spec", ContractSpec.from_yaml_text(_EE_YAML))
    fk = overrides.pop("fk", FKService(_FK_CFG))
    gc = overrides.pop("gripper_convention", SO101Adapter.default_gripper_convention())
    pl = overrides.pop("proprio_layout", SO101Adapter.proprio_layout())
    return InferenceClient(spec=spec, fk=fk, gripper_convention=gc, proprio_layout=pl, **overrides)


def test_encode_state_returns_seven_floats_in_contract_order():
    client = _make_client_so101()
    state = _make_state(joint_pos=np.zeros(6))
    out = client._encode_state(state)
    assert len(out) == 7
    # First 3 = ee_pos, next 3 = ee_rotvec, last 1 = gripper.
    # Concrete values: SO101 at q=0 deg → FK gives a specific pose; assert
    # they match FK(zeros) to prove we're not returning hardcoded zeros.
    expected_T = FKService(_FK_CFG).matrix(np.zeros(5))
    np.testing.assert_allclose(out[:3], expected_T[:3, 3].tolist(), atol=1e-6)
    expected_rotvec = R.from_matrix(expected_T[:3, :3]).as_rotvec().tolist()
    np.testing.assert_allclose(out[3:6], expected_rotvec, atol=1e-6)
    assert out[6] == pytest.approx(0.0, abs=1e-6)  # gripper raw=0 → normalized 0.0


def test_encode_state_skips_fk_when_ee_pre_populated(monkeypatch):
    client = _make_client_so101()
    calls: list = []
    monkeypatch.setattr(client.fk, "matrix", lambda q: (calls.append(q), np.eye(4))[1])

    ee_pos = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    ee_rotvec = np.array([0.0, 0.0, 0.5], dtype=np.float32)
    state = _make_state(joint_pos=np.zeros(6), ee_pos=ee_pos, ee_rotvec=ee_rotvec)
    out = client._encode_state(state)

    assert len(calls) == 0
    np.testing.assert_allclose(out[:3], ee_pos.tolist(), atol=1e-6)
    np.testing.assert_allclose(out[3:6], ee_rotvec.tolist(), atol=1e-6)


def test_encode_state_calls_fk_exactly_once_for_both_components(monkeypatch):
    client = _make_client_so101()
    calls: list = []
    real_matrix = client.fk.matrix
    monkeypatch.setattr(client.fk, "matrix", lambda q: (calls.append(q.copy()), real_matrix(q))[1])
    state = _make_state(joint_pos=np.array([0.1] * 6))
    client._encode_state(state)
    assert len(calls) == 1


def test_encode_state_raises_when_ee_required_but_fk_missing():
    spec = ContractSpec.from_yaml_text(_EE_YAML)
    client = InferenceClient(spec=spec, fk=None)
    state = _make_state(joint_pos=np.zeros(6))
    with pytest.raises(ValueError, match="ee_pos/ee_rotvec"):
        client._encode_state(state)


def test_gripper_without_convention_or_layout_raises():
    """Per spec §3.3: state.gripper_pos has no normalized-unit contract
    per adapter, so the client MUST refuse to encode gripper without an
    explicit convention + layout. No silent fallback."""
    spec = ContractSpec.from_yaml_text(_EE_YAML)
    fk = FKService(_FK_CFG)
    client = InferenceClient(spec=spec, fk=fk)  # no convention/layout
    state = _make_state(joint_pos=np.zeros(6))
    with pytest.raises(ValueError, match="gripper_convention / proprio_layout"):
        client._encode_state(state)


def test_gripper_normalized_from_joint_pos_column():
    """SO101: gripper raw 0..100 packed at joint_pos[5]. raw=50 → 0.5."""
    client = _make_client_so101()
    joint_pos = np.zeros(6); joint_pos[5] = 50.0
    state = _make_state(joint_pos=joint_pos)
    out = client._encode_state(state)
    assert out[6] == pytest.approx(0.5, abs=1e-6)


@pytest.mark.parametrize("raw,expected", [(-10.0, 0.0), (0.0, 0.0), (50.0, 0.5), (100.0, 1.0), (200.0, 1.0)])
def test_gripper_normalization_clips_to_unit_interval(raw, expected):
    client = _make_client_so101()
    joint_pos = np.zeros(6); joint_pos[5] = raw
    state = _make_state(joint_pos=joint_pos)
    assert client._encode_state(state)[6] == pytest.approx(expected, abs=1e-6)


def test_gripper_from_state_gripper_pos_column():
    """reBot-style: raw gripper lives in state.gripper_pos. With convention
    closed_at=0, open_at=1, raw value passes through normalization."""
    pl = ProprioLayout(
        columns=("observation.state.joint_pos", "observation.state.gripper_pos"),
        output_names=("j0","j1","j2","j3","j4","gripper"),
        gripper_via_column="observation.state.gripper_pos",
        gripper_index_in_column=0,
    )
    gc = GripperConvention(closed_at=0.0, open_at=1.0)
    client = _make_client_so101(gripper_convention=gc, proprio_layout=pl)

    state = _make_state(joint_pos=np.zeros(6), gripper_pos=0.7)
    assert client._encode_state(state)[6] == pytest.approx(0.7, abs=1e-6)


def test_gripper_from_state_gripper_pos_column_raises_when_none():
    pl = ProprioLayout(
        columns=("observation.state.joint_pos", "observation.state.gripper_pos"),
        output_names=("j0","j1","j2","j3","j4","gripper"),
        gripper_via_column="observation.state.gripper_pos",
        gripper_index_in_column=0,
    )
    gc = GripperConvention(closed_at=0.0, open_at=1.0)
    client = _make_client_so101(gripper_convention=gc, proprio_layout=pl)
    state = _make_state(joint_pos=np.zeros(6), gripper_pos=None)
    with pytest.raises(ValueError, match="state.gripper_pos is None"):
        client._encode_state(state)


def test_gripper_index_out_of_range_raises():
    pl = ProprioLayout(
        columns=("observation.state.joint_pos",),
        output_names=("j0","j1","j2","j3","j4","gripper"),
        gripper_via_column="observation.state.joint_pos",
        gripper_index_in_column=99,
    )
    gc = GripperConvention(closed_at=0.0, open_at=100.0)
    client = _make_client_so101(gripper_convention=gc, proprio_layout=pl)
    state = _make_state(joint_pos=np.zeros(6))
    with pytest.raises(ValueError, match="out of range"):
        client._encode_state(state)


def test_build_request_body_raises_when_required_image_missing():
    """The so101_v46 contract requires both front and wrist; missing one
    must raise, not silently drop the field."""
    yaml_two_cams = _EE_YAML.replace(
        "images: { front: { field: image_primary, encoding: jpeg_base64, resize: [16,16], jpeg_quality: 90 } }",
        "images:\n    front: { field: image_primary, encoding: jpeg_base64, resize: [16,16], jpeg_quality: 90 }\n"
        "    wrist: { field: image_wrist, encoding: jpeg_base64, resize: [16,16], jpeg_quality: 90 }",
    )
    spec = ContractSpec.from_yaml_text(yaml_two_cams)
    client = _make_client_so101(spec=spec)

    img = np.zeros((16, 16, 3), dtype=np.uint8)
    frames = {"front": Stamped(value=Frame(image=img, t_mono_ns=0), t_mono_ns=0)}
    state = _make_state(joint_pos=np.zeros(6))

    with pytest.raises(ValueError, match="image role 'wrist'"):
        client._build_request_body(frames, state, "pick", {})
