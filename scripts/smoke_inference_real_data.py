"""Smoke test the inference pipeline against real recorded data.

Loads frame 0 of `datasets/SO101/data/chunk-000/episode_000000.parquet` plus
the corresponding front+wrist mp4 frames, boots a FakeVLAServer (returns
mild ee_delta chunks), runs ONE InferenceClient.predict() round trip, then
ActionDecoder.decode() through the real FK + IK on the so101 URDF.

Usage (from repo root):
    env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python scripts/smoke_inference_real_data.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq
import yaml as _yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT))

from mimicrec.inference.action_decoder import ActionDecoder  # noqa: E402
from mimicrec.inference.client import InferenceClient  # noqa: E402
from mimicrec.inference.contract import ContractSpec  # noqa: E402
from mimicrec.kinematics.fk import FKService, KinematicsConfig  # noqa: E402
from mimicrec.kinematics.ik import IKService  # noqa: E402
from mimicrec.types import Frame, RobotState, Stamped  # noqa: E402

from tests.fixtures.fake_vla_server import FakeVLAServer  # noqa: E402


DATASET = REPO_ROOT / "datasets" / "SO101"
URDF = REPO_ROOT / "configs" / "urdf" / "so101" / "so101.urdf"
CONFIG_YAML = REPO_ROOT / "configs" / "inference" / "gemma_libero_v1.yaml"


def read_first_video_frame(mp4: Path) -> np.ndarray:
    cap = cv2.VideoCapture(str(mp4))
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise RuntimeError(f"could not read frame 0 from {mp4}")
    return frame  # BGR HxWx3 uint8


def load_first_state(parquet_path: Path) -> RobotState:
    t = pq.read_table(parquet_path)
    row = t.slice(0, 1).to_pylist()[0]
    joint_pos = np.asarray(row["observation.state.joint_pos"], dtype=np.float64)
    joint_vel = np.asarray(row["observation.state.joint_vel"], dtype=np.float64)
    joint_effort = np.asarray(row["observation.state.joint_effort"], dtype=np.float64)
    gripper_pos = float(row["observation.state.gripper_pos"])
    return RobotState(
        joint_pos=joint_pos,
        joint_vel=joint_vel,
        joint_effort=joint_effort,
        gripper_pos=gripper_pos,
        t_mono_ns=int(row["observation.state.t_mono_ns"]),
    )


def build_contract_against_fake(server_url: str) -> ContractSpec:
    """Load the real gemma_libero_v1.yaml but redirect endpoint at the fake
    server and disable client-side normalization (fake server returns
    physical units)."""
    d = _yaml.safe_load(CONFIG_YAML.read_text())
    d["endpoint"]["url"] = server_url
    d["endpoint"]["headers"] = {}  # avoid env-var interpolation
    d["response"]["action"]["normalization"] = {"method": "none"}
    return ContractSpec.from_yaml_text(_yaml.safe_dump(d))


async def main() -> int:
    # --- Sanity ---
    if not DATASET.exists():
        print(f"❌ dataset not found: {DATASET}")
        return 1
    front_mp4 = DATASET / "videos" / "observation.images.front" / "chunk-000" / "episode_000000.mp4"
    wrist_mp4 = DATASET / "videos" / "observation.images.wrist" / "chunk-000" / "episode_000000.mp4"
    parquet = DATASET / "data" / "chunk-000" / "episode_000000.parquet"
    for p in (front_mp4, wrist_mp4, parquet, URDF):
        if not p.exists():
            print(f"❌ missing: {p}")
            return 1

    # --- Load real inputs ---
    print(f"reading frame 0 from {front_mp4.relative_to(REPO_ROOT)}")
    front = read_first_video_frame(front_mp4)
    print(f"reading frame 0 from {wrist_mp4.relative_to(REPO_ROOT)}")
    wrist = read_first_video_frame(wrist_mp4)
    print(f"  front shape: {front.shape} dtype={front.dtype}")
    print(f"  wrist shape: {wrist.shape} dtype={wrist.dtype}")

    print(f"reading state from {parquet.relative_to(REPO_ROOT)}")
    state_val = load_first_state(parquet)
    print(f"  joint_pos (6): {state_val.joint_pos.tolist()}")
    print(f"  gripper_pos:   {state_val.gripper_pos}")

    # --- Build kinematics on the real URDF ---
    cfg = KinematicsConfig(
        urdf_path=str(URDF),
        target_frame="gripper_frame_link",
        joint_names=["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"],
    )
    print(f"building FK + IK from {URDF.relative_to(REPO_ROOT)}")
    fk = FKService(cfg)
    ik = IKService(cfg)
    narm = fk.n_kin_joints
    print(f"  Narm = {narm}")

    # --- Boot fake VLA server + run one inference round trip ---
    async with FakeVLAServer(chunk_size=8) as srv:
        print(f"fake VLA server up at {srv.url}")
        contract = build_contract_against_fake(srv.url)
        print(f"contract loaded: name={contract.name} chunk_size={contract.response.chunk.expected_size}")

        client = InferenceClient(spec=contract)
        try:
            frames = {
                "front": Stamped(value=Frame(image=front, t_mono_ns=1), t_mono_ns=1),
                "wrist": Stamped(value=Frame(image=wrist, t_mono_ns=1), t_mono_ns=1),
            }
            state = Stamped(value=state_val, t_mono_ns=2)
            instr = Stamped(value="pick the bottle", t_mono_ns=3)

            print("calling client.predict() ...")
            import time
            t0 = time.perf_counter()
            resp = await client.predict(frames, state, instr,
                                        extras={"_t_mono_ns": {"state": state_val.t_mono_ns}})
            t1 = time.perf_counter()
            print(f"  HTTP round-trip: {(t1 - t0) * 1000:.1f} ms")
            print(f"  fake server received {srv.calls} call(s)")
            req_body = srv.received[0]
            print(f"  request keys: {sorted(req_body.keys())}")
            print(f"  proprio length: {len(req_body['proprio'])} (expected 7 = 6 joints incl. gripper packed + 1 gripper_pos)")
            print(f"  image_primary base64 size: {len(req_body['image_primary'])} chars (~{len(req_body['image_primary']) * 3 // 4} bytes JPEG)")
            print(f"  response actions: {len(resp['actions'])} steps × {len(resp['actions'][0])} dims")

            # --- Decode through real ActionDecoder + real IK ---
            decoder = ActionDecoder(spec=contract, fk=fk, ik=ik, narm=narm, action_stats=None)
            print("decoding chunk through ActionDecoder + real IK ...")
            t0 = time.perf_counter()
            chunk = decoder.decode(resp, current_state=state_val)
            t1 = time.perf_counter()
            print(f"  decoded {len(chunk)} steps in {(t1 - t0) * 1000:.1f} ms total")
            ik_failures = sum(1 for s in chunk if s.ik_failed)
            print(f"  IK failures: {ik_failures}/{len(chunk)}")
            if ik_failures == len(chunk):
                print("  WARNING: every step failed IK — check workspace bounds")

            # First & last step joint targets (degrees)
            print(f"  step 0 q: {[f'{v:.2f}' for v in chunk[0].q.tolist()]}")
            print(f"  step -1 q: {[f'{v:.2f}' for v in chunk[-1].q.tolist()]}")
            print(f"  step 0 gripper: {chunk[0].gripper}")

            # Sanity: first step's q should be close to seed (small ee_delta)
            seed_q = state_val.joint_pos[:narm]
            first_q = chunk[0].q
            joint_drift = float(np.abs(first_q - seed_q).max())
            print(f"  step 0 joint drift from seed: {joint_drift:.3f} deg "
                  f"({'OK' if joint_drift < 5.0 else 'high — check'})")

            print("\n✅ inference mock pipeline works end-to-end with real data.")
            return 0
        finally:
            await client.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
