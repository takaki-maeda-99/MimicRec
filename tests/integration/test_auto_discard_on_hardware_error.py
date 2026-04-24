from __future__ import annotations
import asyncio
from pathlib import Path

import pytest

from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.adapters.mock_teleop import MockTeleoperator
from mimicrec.cameras.mock_camera import MockCamera
from mimicrec.cameras.manager import CameraManager
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.lifecycle import SessionManager
from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.types import SessionMode, SessionState
from mimicrec.util.error_bus import ErrorBus


@pytest.mark.asyncio
async def test_hardware_error_during_recording_auto_discards(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=["front"])

    cam = MockCamera("front")
    cam.drop_next = 3
    bus = ErrorBus()
    cm = CameraManager(cameras={"front": cam}, error_bus=bus)

    sm = SessionManager(
        dataset_root=ds,
        robot=MockRobotAdapter(), teleop=MockTeleoperator(dof=2),
        mapper=IdentityMapper(), cameras=cm,
        mode=SessionMode.TELEOP, fps=30, error_bus=bus,
        resolved_config={}, replay_safety=None,
    )
    await sm.start()
    await sm.episode_start()
    # Camera drops will produce HardwareErrors via CameraManager -> ErrorBus.
    # The error handler should auto-discard the pending episode.
    # Wait for the camera errors to propagate and trigger auto-discard.
    for _ in range(50):
        if sm.state == SessionState.READY:
            break
        await asyncio.sleep(0.05)

    assert sm.state == SessionState.READY
    paths = dataset_paths(ds)
    assert not (paths.data_dir / "chunk-000" / "episode_000000.parquet").exists()

    await sm.end()
