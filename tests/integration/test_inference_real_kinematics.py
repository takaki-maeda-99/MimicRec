"""Integration test that exercises the inference subsystem with the REAL
SO-101 FK/IK on the real URDF — not the _StubFK/_StubIK used by
`make_inference_session`. Catches IK initialization issues, URDF load
problems, and real-IK convergence behavior that the stubs hide.

This sits alongside `test_inference_lifecycle.py` (which uses the stub
fixture for fast lifecycle assertions). Run with:

    cd backend && env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python \
        -m pytest ../tests/integration/test_inference_real_kinematics.py -v
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest
import yaml as _yaml

from mimicrec.inference.action_decoder import ActionDecoder
from mimicrec.inference.contract import ContractSpec
from mimicrec.kinematics.fk import FKService, KinematicsConfig
from mimicrec.kinematics.ik import IKService
from mimicrec.types import RobotState

REPO_ROOT = Path(__file__).resolve().parents[2]
URDF = REPO_ROOT / "configs" / "urdf" / "so101" / "so101.urdf"


@pytest.fixture(scope="module")
def so101_kinematics() -> tuple[FKService, IKService]:
    """Real FKService + IKService against the SO-101 URDF.

    Module-scope so we don't pay placo init cost per test.
    """
    cfg = KinematicsConfig(
        urdf_path=str(URDF),
        target_frame="gripper_frame_link",
        joint_names=[
            "shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll",
        ],
    )
    fk = FKService(cfg)
    ik = IKService(cfg)
    return fk, ik


def _build_contract_yaml(server_url: str = "http://example.invalid/predict") -> str:
    return _yaml.safe_dump({
        "name": "test_contract",
        "description": "real-kinematics integration test",
        "endpoint": {
            "url": server_url, "method": "POST",
            "retry": {"max_attempts": 0},
        },
        "request": {
            "images": {"front": {
                "field": "image_primary", "encoding": "jpeg_base64",
                "resize": [16, 16], "jpeg_quality": 90,
            }},
            "state": {
                "field": "proprio",
                "components": ["joint_pos", "gripper_pos"],
                "normalization": {"method": "none"},
            },
            "instruction": {"field": "instruction"},
        },
        "response": {
            "actions_path": "actions",
            "chunk": {"expected_size": 4, "on_size_mismatch": "use_actual"},
            "action": {
                "type": "ee_delta", "frame": "ee_local",
                "pose": {"units": "meter_axisangle_rad"},
                "gripper": {"kind": "absolute", "units": "normalized_0_1"},
                "components": ["ee_delta", "gripper"],
                "normalization": {"method": "none"},
            },
        },
        "loop": {"prefetch_threshold": 0.5, "max_inflight": 1},
    })


def _state_at_seed_pose() -> RobotState:
    """SO-101 first-frame-of-episode-0 seed pose (degrees), copied from
    the recorded SO101 dataset for realism."""
    return RobotState(
        joint_pos=np.array([-8.31, -93.71, 96.44, 61.05, 20.88, 4.26], dtype=np.float64),
        joint_vel=np.zeros(6, dtype=np.float64),
        joint_effort=np.zeros(6, dtype=np.float64),
        gripper_pos=4.26,
        t_mono_ns=0,
    )


def test_real_ik_round_trip_at_seed_pose(so101_kinematics):
    """FK(seed) → T, IK(T, seed) → q' should reproduce seed (within tolerance)."""
    fk, ik = so101_kinematics
    seed = _state_at_seed_pose().joint_pos[:5]
    T = fk._k.forward_kinematics(seed)
    q, ok = ik.solve(T, seed=seed)
    assert ok, "IK must converge for FK-derived target at seed pose"
    assert np.allclose(q, seed, atol=0.5), \
        f"IK round-trip drifted: {(q - seed).tolist()}"


def test_real_decoder_chunk_through_real_ik(so101_kinematics):
    """Run a small chunk of mild ee_deltas through the real ActionDecoder
    + real IK. All steps should converge; first step's joint drift from
    seed should be modest (< 5° for 1 mm position deltas)."""
    fk, ik = so101_kinematics
    spec = ContractSpec.from_yaml_text(_build_contract_yaml())
    decoder = ActionDecoder(spec=spec, fk=fk, ik=ik, narm=5, action_stats=None)

    state = _state_at_seed_pose()
    raw = {"actions": [
        # +1mm in x per step (ee_local frame), gripper held mid
        [0.001, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5],
        [0.001, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5],
        [0.001, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5],
        [0.001, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5],
    ]}
    chunk = decoder.decode(raw, current_state=state)
    assert len(chunk) == 4
    ik_failures = [s.ik_failed for s in chunk]
    assert not any(ik_failures), \
        f"real IK failed on at least one step (small ee_delta should converge): {ik_failures}"

    # First step should be close to seed (small delta)
    seed = state.joint_pos[:5]
    drift = float(np.abs(chunk[0].q - seed).max())
    assert drift < 5.0, f"step 0 drift {drift:.2f}° exceeds 5° threshold"


def test_real_ik_drift_revert_on_failure(so101_kinematics):
    """Verify the decoder's IK-fail T_curr revert (action_decoder.py fix
    from round-5 follow-up) actually keeps T_curr aligned with the seed
    pose's FK after a failure. Force a failure by feeding a huge delta.
    Subsequent steps must remain solvable from the seed, not blow up."""
    fk, ik = so101_kinematics
    spec = ContractSpec.from_yaml_text(_build_contract_yaml())
    decoder = ActionDecoder(spec=spec, fk=fk, ik=ik, narm=5, action_stats=None)

    state = _state_at_seed_pose()
    # Step 0: huge unreachable delta (forces IK fail). Step 1: tiny delta.
    raw = {"actions": [
        [10.0, 10.0, 10.0, 0.0, 0.0, 0.0, 0.5],   # 10 m away — definitely fails
        [0.001, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5],   # 1 mm — should converge cleanly
    ]}
    chunk = decoder.decode(raw, current_state=state)

    assert chunk[0].ik_failed, "step 0 should fail IK on a 10m+ target"
    # step 1 must succeed because T_curr was reverted to FK(seed) after step 0,
    # so step 1 is solving for a 1mm-from-seed pose, not 1mm-from-fictional-T_next.
    assert not chunk[1].ik_failed, \
        "step 1 must succeed after step 0 failure — T_curr revert is the fix"
