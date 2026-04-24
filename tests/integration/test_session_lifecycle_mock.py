from __future__ import annotations
import asyncio
from pathlib import Path

import pytest

from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.adapters.mock_teleop import MockTeleoperator
from mimicrec.cameras.mock_camera import MockCamera
from mimicrec.cameras.manager import CameraManager
from mimicrec.errors import InvalidTransitionError
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.lifecycle import SessionManager
from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.types import SessionMode, SessionState
from mimicrec.util.error_bus import ErrorBus


@pytest.mark.asyncio
async def test_full_teleop_flow(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=["front"])
    robot = MockRobotAdapter()
    teleop = MockTeleoperator(dof=2)
    bus = ErrorBus()
    cm = CameraManager(cameras={"front": MockCamera("front")}, error_bus=bus)
    sm = SessionManager(
        dataset_root=ds,
        robot=robot, teleop=teleop, mapper=IdentityMapper(),
        cameras=cm, mode=SessionMode.TELEOP, fps=30, error_bus=bus,
        resolved_config={},
        replay_safety=None,
    )

    await sm.start()
    assert sm.state == SessionState.READY

    await sm.episode_start()
    assert sm.state == SessionState.RECORDING
    await asyncio.sleep(0.2)

    await sm.episode_stop()
    assert sm.state == SessionState.REVIEW

    await sm.episode_save(success=True, comment="ok")
    assert sm.state == SessionState.READY

    paths = dataset_paths(ds)
    assert (paths.data_dir / "chunk-000" / "episode_000000.parquet").exists()

    # Attempting episode_start during replay must fail
    sm.session.replay_active = True
    with pytest.raises(InvalidTransitionError):
        await sm.episode_start()
    sm.session.replay_active = False

    await sm.end()
    assert sm.state == SessionState.IDLE
