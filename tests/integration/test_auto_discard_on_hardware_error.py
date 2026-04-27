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
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.types import SessionMode, SessionState
from mimicrec.util.error_bus import ErrorBus


@pytest.mark.asyncio
async def test_transient_camera_error_does_not_kill_recording(tmp_path: Path):
    """A few dropped camera frames must NOT discard the in-flight episode.

    Earlier behaviour auto-discarded on every HardwareError, which meant a
    single V4L2 timeout (very common on USB cameras) threw away an entire
    hand-teach session. The camera task already retries on its own, the
    parquet writer skips the missing video frame for that tick, and the
    recording stays well-formed — so error handling here just logs and
    lets the operator decide when to stop.
    """
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=["front"])

    cam = MockCamera("front")
    cam.drop_next = 3   # 3 transient errors, then resume normal frames
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

    # Wait long enough for the camera drops to propagate and for the
    # recording loop to capture frames after the camera recovers.
    await asyncio.sleep(0.5)

    # Recording must still be active — transient errors don't auto-discard.
    assert sm.state == SessionState.RECORDING

    await sm.episode_stop()
    await sm.end()
