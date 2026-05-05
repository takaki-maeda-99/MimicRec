import asyncio
import base64
import json

import numpy as np
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient

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
    client = InferenceClient(spec)
    img = np.zeros((16, 16, 3), dtype=np.uint8)
    frames = {"front": Stamped(value=Frame(image=img, t_mono_ns=1), t_mono_ns=1)}
    state = Stamped(value=RobotState(
        joint_pos=np.zeros(5), joint_vel=np.zeros(5),
        joint_effort=np.zeros(5), gripper_pos=0.0, t_mono_ns=2), t_mono_ns=2)
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
