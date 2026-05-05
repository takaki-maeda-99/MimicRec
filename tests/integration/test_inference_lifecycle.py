"""Integration tests for SessionMode.INFERENCE lifecycle.

These tests exercise start_inference_session, 409-on-active-session,
and pause/resume helpers. They depend on fixtures (fake_vla_server,
make_inference_session) defined in tests/conftest.py (Task 26).
"""
import asyncio
import pytest

from mimicrec.errors import InvalidTransitionError
from mimicrec.types import SessionMode, SessionState


async def _wait_for(predicate, timeout=5.0, step=0.02):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(step)
    return False


async def test_start_inference_against_mock_robot(make_inference_session):
    sm = await make_inference_session(instruction="pick X")
    assert sm.session.mode == SessionMode.INFERENCE
    assert sm.session.state == SessionState.READY
    assert sm._producer_task is not None and not sm._producer_task.done()
    assert sm._control_loop_task is not None and not sm._control_loop_task.done()
    assert sm._dispatcher_task is not None and not sm._dispatcher_task.done()
    assert sm._writer_task is not None and not sm._writer_task.done()


async def test_409_when_session_already_active(make_inference_session):
    sm = await make_inference_session(instruction="x")
    # Already in INFERENCE mode; another start_inference_session must fail.
    contract = sm._inference_client.spec
    with pytest.raises(InvalidTransitionError):
        await sm.start_inference_session(
            contract=contract, instruction="y",
            inference_config_name="test_contract",
        )


async def test_pause_and_resume_helpers(make_inference_session):
    sm = await make_inference_session(instruction="x")
    # Wait for producer to fill the buffer at least once.
    assert await _wait_for(lambda: sm._chunk_buffer.depth() > 0, timeout=5.0)
    # Pause + flush; depth must drop to 0 and flushed must reflect what was there.
    flushed = sm.pause_producer_and_flush()
    assert flushed > 0
    assert sm._chunk_buffer.depth() == 0
    assert sm.session.producer_paused is True
    # Resume; producer must re-arm and refill.
    sm.resume_producer()
    assert sm.session.producer_paused is False
    assert await _wait_for(lambda: sm._chunk_buffer.depth() > 0, timeout=5.0)


class _StubFK:
    """Inline copy of conftest's _StubFK so tests that construct SessionManager
    directly (rather than via the make_inference_session fixture) can pass it
    in. Kept tiny — just enough to satisfy the FKLike protocol."""
    cfg = object()
    n_kin_joints: int = 2

    def matrix(self, q):
        import numpy as np
        return np.eye(4)

    def pose(self, q):
        import numpy as np
        return np.zeros(3, dtype=np.float32), np.zeros(3, dtype=np.float32)


class _StubIK:
    def solve(self, T, seed):
        return seed.copy(), True


def _patch_decoder_and_ik(monkeypatch, stub_fk, stub_ik):
    """Replicate the conftest fixture's IKService / ActionDecoder patching
    for tests that bypass `make_inference_session`."""
    from mimicrec.inference import action_decoder as _ad_mod
    _orig = _ad_mod.ActionDecoder

    class _Patched(_orig):
        def __init__(self, *, spec, fk, ik, narm, action_stats=None):
            super().__init__(spec=spec, fk=stub_fk, ik=stub_ik, narm=narm,
                             action_stats=action_stats)

    monkeypatch.setattr("mimicrec.session.lifecycle.ActionDecoder", _Patched)
    monkeypatch.setattr("mimicrec.session.lifecycle.IKService", lambda cfg: stub_ik)


async def test_replay_task_alive_blocks_inference_start(make_inference_session, fake_vla_server, tmp_path, monkeypatch):
    """Regression: GPT-5.5 round 3 found that replay_active is set INSIDE
    run_replay (not synchronously by replay_start), so a freshly-spawned
    replay task can have _replay_task != None while replay_active==False.
    The fix added a `_replay_task is not None and not done()` check.
    Verify the check actually catches that window."""
    from mimicrec.adapters.mock_robot import MockRobotAdapter
    from mimicrec.adapters.mock_teleop import MockTeleoperator
    from mimicrec.cameras.manager import CameraManager
    from mimicrec.cameras.mock_camera import MockCamera
    from mimicrec.mappers.identity import IdentityMapper
    from mimicrec.session.lifecycle import SessionManager
    from mimicrec.recording.dataset_layout import init_dataset
    from mimicrec.util.error_bus import ErrorBus
    from mimicrec.inference.contract import ContractSpec
    from mimicrec.errors import InvalidTransitionError
    import yaml as _yaml
    import json

    # Set up MIMICREC_VLA_DEST_ROOT for stats resolution
    monkeypatch.setenv("MIMICREC_VLA_DEST_ROOT", str(tmp_path))
    meta = tmp_path / "SO101" / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "action_stats.json").write_text(json.dumps({"mean": [0.0]*7, "std": [0.001]*7}))

    stub_fk, stub_ik = _StubFK(), _StubIK()
    _patch_decoder_and_ik(monkeypatch, stub_fk, stub_ik)

    robot = MockRobotAdapter()
    bus = ErrorBus()
    cm = CameraManager(cameras={"front": MockCamera("front")}, error_bus=bus)
    ds = tmp_path / "ds_replay_race"
    init_dataset(ds, fps=30, joint_names=list(robot.joint_names), camera_names=["front"])

    sm = SessionManager(
        dataset_root=ds,
        robot=robot, teleop=MockTeleoperator(dof=2), mapper=IdentityMapper(),
        cameras=cm, mode=SessionMode.TELEOP, fps=30, error_bus=bus,
        resolved_config={"robot": {"inference_safety": {
            "max_joint_delta_per_step_deg": 5.0,
            "slow_stop_ticks": 5,
            "joint_limits_deg": {n: [-180.0, 180.0] for n in robot.joint_names},
        }}},
        replay_safety=None,
        fk=stub_fk,
    )
    await sm.start()

    # Simulate the "replay task spawned but body hasn't run yet" window:
    # replay_active is False but _replay_task is alive. (We don't run the
    # real replay body here — just need _replay_task to be a live Task.)
    async def _dummy_replay():
        await asyncio.sleep(10)

    sm._replay_task = asyncio.create_task(_dummy_replay())
    assert sm.session.replay_active is False  # the racy window
    assert not sm._replay_task.done()

    contract_text = _yaml.safe_dump(_yaml.safe_load(_yaml.safe_dump({
        "name": "t", "endpoint": {"url": fake_vla_server.url, "method": "POST",
            "retry": {"max_attempts": 0}},
        "request": {
            "images": {"front": {"field": "img", "encoding": "jpeg_base64",
                                 "resize": [16, 16], "jpeg_quality": 90}},
            "state": {"field": "p", "components": ["joint_pos", "gripper_pos"],
                      "normalization": {"method": "none"}},
            "instruction": {"field": "i"},
        },
        "response": {
            "actions_path": "actions",
            "chunk": {"expected_size": 4, "on_size_mismatch": "use_actual"},
            "action": {"type": "ee_delta", "frame": "ee_local",
                       "pose": {"units": "meter_axisangle_rad"},
                       "gripper": {"kind": "absolute", "units": "normalized_0_1"},
                       "components": ["ee_delta", "gripper"],
                       "normalization": {"method": "none"}},
        },
        "loop": {"prefetch_threshold": 0.5, "max_inflight": 1},
    })))
    contract = ContractSpec.from_yaml_text(contract_text)

    # The fix: even though replay_active is False, the alive _replay_task
    # must cause start_inference_session to reject.
    with pytest.raises(InvalidTransitionError, match="replay"):
        await sm.start_inference_session(
            contract=contract, instruction="x", inference_config_name="t",
        )

    # Cleanup
    sm._replay_task.cancel()
    try:
        await sm._replay_task
    except (asyncio.CancelledError, Exception):
        pass
    sm._replay_task = None
    await sm.end()


async def test_handteach_to_inference_sets_position_mode(tmp_path, fake_vla_server, monkeypatch):
    """Regression: GPT-5.5 round 1 found that bootstrapping from a
    HAND_TEACH session left the robot in GRAVITY_COMP because
    start_inference_session didn't call set_mode(POSITION). Verify the
    explicit set_mode call is wired through."""
    from mimicrec.adapters.mock_robot import MockRobotAdapter
    from mimicrec.adapters.robot import RobotMode
    from mimicrec.cameras.manager import CameraManager
    from mimicrec.cameras.mock_camera import MockCamera
    from mimicrec.mappers.identity import IdentityMapper
    from mimicrec.session.lifecycle import SessionManager
    from mimicrec.recording.dataset_layout import init_dataset
    from mimicrec.util.error_bus import ErrorBus
    from mimicrec.inference.contract import ContractSpec
    import yaml as _yaml
    import json

    monkeypatch.setenv("MIMICREC_VLA_DEST_ROOT", str(tmp_path))
    meta = tmp_path / "SO101" / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "action_stats.json").write_text(json.dumps({"mean": [0.0]*7, "std": [0.001]*7}))

    stub_fk, stub_ik = _StubFK(), _StubIK()
    _patch_decoder_and_ik(monkeypatch, stub_fk, stub_ik)

    # Wrap MockRobotAdapter to support GRAVITY_COMP (mock by default supports
    # POSITION + GRAVITY_COMP via set_mode storing the value).
    robot = MockRobotAdapter()
    bus = ErrorBus()
    cm = CameraManager(cameras={"front": MockCamera("front")}, error_bus=bus)
    ds = tmp_path / "ds_handteach"
    init_dataset(ds, fps=30, joint_names=list(robot.joint_names), camera_names=["front"])

    sm = SessionManager(
        dataset_root=ds,
        robot=robot, teleop=None, mapper=IdentityMapper(),
        cameras=cm, mode=SessionMode.HAND_TEACH, fps=30, error_bus=bus,
        resolved_config={"robot": {"inference_safety": {
            "max_joint_delta_per_step_deg": 5.0,
            "slow_stop_ticks": 5,
            "joint_limits_deg": {n: [-180.0, 180.0] for n in robot.joint_names},
        }}},
        replay_safety=None,
        fk=stub_fk,
    )
    await sm.start()
    # After hand-teach start, the robot is set to GRAVITY_COMP (or whatever the
    # adapter falls back to if it doesn't support gravity comp).
    pre_mode = robot._mode

    contract_text = _yaml.safe_dump({
        "name": "t", "endpoint": {"url": fake_vla_server.url, "method": "POST",
            "retry": {"max_attempts": 0}},
        "request": {
            "images": {"front": {"field": "img", "encoding": "jpeg_base64",
                                 "resize": [16, 16], "jpeg_quality": 90}},
            "state": {"field": "p", "components": ["joint_pos", "gripper_pos"],
                      "normalization": {"method": "none"}},
            "instruction": {"field": "i"},
        },
        "response": {
            "actions_path": "actions",
            "chunk": {"expected_size": 4, "on_size_mismatch": "use_actual"},
            "action": {"type": "ee_delta", "frame": "ee_local",
                       "pose": {"units": "meter_axisangle_rad"},
                       "gripper": {"kind": "absolute", "units": "normalized_0_1"},
                       "components": ["ee_delta", "gripper"],
                       "normalization": {"method": "none"}},
        },
        "loop": {"prefetch_threshold": 0.5, "max_inflight": 1},
    })
    contract = ContractSpec.from_yaml_text(contract_text)
    await sm.start_inference_session(
        contract=contract, instruction="x", inference_config_name="t",
    )
    # The fix: after start_inference_session, the robot mode MUST be POSITION,
    # regardless of what bootstrap mode it was in.
    assert robot._mode == RobotMode.POSITION, \
        f"start_inference_session must set robot to POSITION, got {robot._mode} (was {pre_mode})"

    await sm.stop_inference_session()
    await sm.end()
