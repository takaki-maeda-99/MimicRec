from __future__ import annotations
import asyncio
import json
from pathlib import Path
from typing import AsyncIterator
import time

import numpy as np
import pytest
import yaml as _yaml

from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.adapters.mock_teleop import MockTeleoperator
from mimicrec.cameras.manager import CameraManager
from mimicrec.cameras.mock_camera import MockCamera
from mimicrec.errors import InvalidTransitionError
from mimicrec.inference.contract import ContractSpec
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.session.lifecycle import SessionManager
from mimicrec.session.state import Session
from mimicrec.types import RobotCommand, RobotState, SampleBundle, SessionMode, SessionState, TeleopAction
from mimicrec.util.clock import FakeClock, RealClock
from mimicrec.util.error_bus import ErrorBus
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics

from tests.fixtures.fake_vla_server import FakeVLAServer


@pytest.fixture
def real_clock():
    return RealClock()


@pytest.fixture
def fake_clock():
    return FakeClock(start_ns=0)


@pytest.fixture
def metrics():
    return Metrics()


@pytest.fixture
def mock_robot():
    return MockRobotAdapter()


@pytest.fixture
def mock_teleop():
    return MockTeleoperator(dof=2)


async def _prime_robot_reader(robot, slot: LatestValue[RobotState]) -> asyncio.Task:
    async def run():
        while True:
            t = time.monotonic_ns()
            st = await robot.read_state()
            st.t_mono_ns = t
            slot.set(st, t_mono_ns=t)
    return asyncio.create_task(run())


async def _prime_teleop_reader(teleop, slot: LatestValue[TeleopAction]) -> asyncio.Task:
    async def run():
        while True:
            t = time.monotonic_ns()
            a = await teleop.read_action()
            a.t_mono_ns = t
            slot.set(a, t_mono_ns=t)
    return asyncio.create_task(run())


# ---------------------------------------------------------------------------
# Inference integration fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def fake_vla_server():
    async with FakeVLAServer(chunk_size=8) as srv:
        yield srv


def _build_contract_yaml(*, server_url: str, normalization: str = "none") -> str:
    d = {
        "name": "test_contract",
        "description": "test",
        "endpoint": {
            "url": server_url, "method": "POST",
            "retry": {"max_attempts": 0},
        },
        "request": {
            "images": {
                "front": {
                    "field": "image_primary", "encoding": "jpeg_base64",
                    "resize": [16, 16], "jpeg_quality": 90,
                },
            },
            "state": {
                "field": "proprio",
                "components": ["joint_pos", "gripper_pos"],
                "normalization": {"method": "none"},
            },
            "instruction": {"field": "instruction"},
        },
        "response": {
            "actions_path": "actions",
            "chunk": {"expected_size": 8, "on_size_mismatch": "use_actual"},
            "action": {
                "type": "ee_delta", "frame": "ee_local",
                "pose": {"units": "meter_axisangle_rad"},
                "gripper": {"kind": "absolute", "units": "normalized_0_1"},
                "components": ["ee_delta", "gripper"],
                "normalization": {"method": normalization},
            },
        },
        "loop": {"prefetch_threshold": 0.5, "max_inflight": 1},
    }
    return _yaml.safe_dump(d)


def _write_action_stats(tmp_path: Path) -> None:
    """Write stats file at ${MIMICREC_VLA_DEST_ROOT}/SO101/meta/action_stats.json."""
    meta = tmp_path / "SO101" / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "action_stats.json").write_text(json.dumps(
        {"mean": [0.0] * 7, "std": [0.001] * 7}
    ))


class _StubFK:
    """Minimal FK that satisfies FKLike (returns identity 4x4).
    Exposes a `cfg` attribute so lifecycle's `IKService(fk.cfg)` call doesn't crash
    (the patched IKService ignores cfg entirely).
    Also exposes `n_kin_joints` and `pose()` so the writer's parquet_row helper
    doesn't crash when fk is set.
    """
    cfg = object()  # opaque sentinel; patched IKService ignores it
    n_kin_joints: int = 2  # matches MockRobotAdapter.joint_names count

    def matrix(self, q: np.ndarray) -> np.ndarray:
        return np.eye(4)

    def pose(self, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return np.zeros(3, dtype=np.float32), np.zeros(3, dtype=np.float32)


class _StubIK:
    """Minimal IK that satisfies IKLike (returns seed unchanged)."""
    def solve(self, T: np.ndarray, seed: np.ndarray) -> tuple[np.ndarray, bool]:
        return seed.copy(), True


@pytest.fixture
async def make_inference_session(tmp_path, fake_vla_server, monkeypatch):
    """Factory fixture. Returns an async callable that builds a fully-running
    SessionManager in INFERENCE mode against the fake VLA server.

    The factory calls sm.start() (TELEOP bootstrap) then cancels the teleop
    control loop and calls sm.start_inference_session(...).

    Caller is responsible for cleanup (or let teardown do it).
    """
    monkeypatch.setenv("MIMICREC_VLA_DEST_ROOT", str(tmp_path))
    _write_action_stats(tmp_path)

    # Patch ActionDecoder in lifecycle to use stub FK/IK instead of real IKService.
    from mimicrec.inference import action_decoder as _ad_mod
    _orig_decoder = _ad_mod.ActionDecoder

    stub_fk = _StubFK()
    stub_ik = _StubIK()

    class _PatchedActionDecoder(_orig_decoder):
        def __init__(self, *, spec, fk, ik, narm, action_stats=None):
            super().__init__(spec=spec, fk=stub_fk, ik=stub_ik, narm=narm, action_stats=action_stats)

    monkeypatch.setattr("mimicrec.session.lifecycle.ActionDecoder", _PatchedActionDecoder)
    # Also patch IKService so lifecycle's `IKService(fk.cfg)` doesn't crash.
    monkeypatch.setattr("mimicrec.session.lifecycle.IKService", lambda cfg: stub_ik)

    created: list[SessionManager] = []

    async def _factory(*, instruction: str = "test instruction", normalization: str = "none"):
        robot = MockRobotAdapter()
        joint_names = list(robot.joint_names)
        ds = tmp_path / "ds"
        if not ds.exists():
            init_dataset(ds, fps=30, joint_names=joint_names, camera_names=["front"])

        teleop = MockTeleoperator(dof=len(joint_names))
        bus = ErrorBus()
        cm = CameraManager(cameras={"front": MockCamera("front")}, error_bus=bus)

        joint_limits = {n: [-180.0, 180.0] for n in joint_names}
        resolved_config = {
            "robot": {
                "inference_safety": {
                    "max_joint_delta_per_step_deg": 5.0,
                    "slow_stop_ticks": 5,
                    "joint_limits_deg": joint_limits,
                },
            },
        }

        sm = SessionManager(
            dataset_root=ds,
            robot=robot, teleop=teleop, mapper=IdentityMapper(),
            cameras=cm, mode=SessionMode.TELEOP, fps=30, error_bus=bus,
            resolved_config=resolved_config,
            replay_safety=None,
            fk=stub_fk,
        )
        created.append(sm)

        await sm.start()  # boots readers + teleop control loop

        # Cancel the teleop control loop before transitioning to inference.
        if sm._control_loop_task is not None:
            sm._control_loop_task.cancel()
            try:
                await sm._control_loop_task
            except (asyncio.CancelledError, Exception):
                pass
            sm._control_loop_task = None

        # Also cancel the teleop dispatcher and writer spawned by start();
        # start_inference_session will spawn fresh ones.
        for attr in ("_dispatcher_task", "_writer_task"):
            t = getattr(sm, attr, None)
            if t is not None:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
                setattr(sm, attr, None)

        contract_text = _build_contract_yaml(
            server_url=fake_vla_server.url, normalization=normalization,
        )
        contract = ContractSpec.from_yaml_text(contract_text)
        await sm.start_inference_session(
            contract=contract,
            instruction=instruction,
            inference_config_name="test_contract",
        )
        return sm

    yield _factory

    for sm in created:
        try:
            await sm.stop_inference_session()
        except Exception:
            pass
        try:
            await sm.end()
        except Exception:
            pass
