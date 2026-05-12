"""End-to-end shape verification: InferenceClient → mocked X-VLA-Adapter
server → ActionDecoder. Confirms a so101_v46-shaped request lands at the
server with the right field names + proprio length + image keys, and that
a well-formed response decodes into joint commands via FK+IK."""
import numpy as np
import pytest
from aiohttp import web
from pathlib import Path

from mimicrec.adapters.so101 import SO101Adapter
from mimicrec.inference.action_decoder import ActionDecoder
from mimicrec.inference.client import InferenceClient
from mimicrec.inference.contract import ContractSpec
from mimicrec.kinematics.fk import FKService, KinematicsConfig
from mimicrec.kinematics.ik import IKService
from mimicrec.types import Frame, RobotState, Stamped


REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT_PATH = REPO_ROOT / "configs" / "inference" / "so101_v46.yaml"
_URDF_PATH = REPO_ROOT / "configs" / "urdf" / "so101" / "so101.urdf"


def _img():
    return np.zeros((16, 16, 3), dtype=np.uint8)


def _state():
    jp = np.zeros(6, dtype=np.float32); jp[5] = 50.0  # gripper raw midpoint
    return RobotState(
        joint_pos=jp,
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
    )


def _build_client_decoder(url: str):
    spec = ContractSpec.from_yaml_text(_CONTRACT_PATH.read_text())
    spec.endpoint.url = url

    fk_cfg = KinematicsConfig(
        urdf_path=str(_URDF_PATH),
        target_frame="gripper_frame_link",
        joint_names=["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll"],
    )
    fk = FKService(fk_cfg); ik = IKService(fk_cfg)
    client = InferenceClient(
        spec=spec, fk=fk,
        gripper_convention=SO101Adapter.default_gripper_convention(),
        proprio_layout=SO101Adapter.proprio_layout(),
    )
    decoder = ActionDecoder(spec=spec, fk=fk, ik=ik, narm=fk.n_kin_joints, action_stats=None)
    return client, decoder


async def test_so101_v46_request_decode_round_trip(aiohttp_client):
    received: dict = {}

    async def handler(request):
        received.update(await request.json())
        return web.json_response({"actions": [[0.001, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5] for _ in range(8)]})

    app = web.Application()
    app.router.add_post("/predict", handler)
    test_client = await aiohttp_client(app)
    url = str(test_client.make_url("/predict"))

    client, decoder = _build_client_decoder(url)

    frames = {
        "front": Stamped(value=Frame(image=_img(), t_mono_ns=0), t_mono_ns=0),
        "wrist": Stamped(value=Frame(image=_img(), t_mono_ns=0), t_mono_ns=0),
    }
    body = await client.predict(
        frames,
        Stamped(value=_state(), t_mono_ns=0),
        Stamped(value="pick up the cube", t_mono_ns=0),
        extras={},
    )
    chunk = decoder.decode(body, _state())

    assert set(received.keys()) >= {"image_primary", "image_wrist", "proprio", "instruction", "model_version"}
    assert len(received["proprio"]) == 7
    assert received["instruction"] == "pick up the cube"
    assert received["model_version"] == "x_vla_so101_v46"
    assert len(chunk) == 8
    for step in chunk:
        assert step.q.shape[0] == 5
        assert 0.0 <= step.gripper <= 1.0
    await client.aclose()


async def test_so101_v46_rejects_wrong_chunk_size(aiohttp_client):
    async def handler(request):
        return web.json_response({"actions": [[0.0]*7 for _ in range(7)]})  # WRONG: 7 rows
    app = web.Application()
    app.router.add_post("/predict", handler)
    test_client = await aiohttp_client(app)
    url = str(test_client.make_url("/predict"))

    client, decoder = _build_client_decoder(url)

    frames = {
        "front": Stamped(value=Frame(image=_img(), t_mono_ns=0), t_mono_ns=0),
        "wrist": Stamped(value=Frame(image=_img(), t_mono_ns=0), t_mono_ns=0),
    }
    body = await client.predict(
        frames,
        Stamped(value=_state(), t_mono_ns=0),
        Stamped(value="x", t_mono_ns=0),
        extras={},
    )
    with pytest.raises(ValueError, match="chunk size 7 != expected 8"):
        decoder.decode(body, _state())
    await client.aclose()
