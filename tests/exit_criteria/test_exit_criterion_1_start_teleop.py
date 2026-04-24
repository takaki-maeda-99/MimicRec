from __future__ import annotations
from pathlib import Path

from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.adapters.mock_teleop import MockTeleoperator
from mimicrec.cameras.mock_camera import MockCamera
from mimicrec.cameras.manager import CameraManager
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.lifecycle import SessionManager
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.types import SessionMode, SessionState
from mimicrec.util.error_bus import ErrorBus


async def test_exit_criterion_1_session_starts_in_teleop(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=["front"])
    bus = ErrorBus()
    cm = CameraManager(cameras={"front": MockCamera("front")}, error_bus=bus)
    sm = SessionManager(
        dataset_root=ds, robot=MockRobotAdapter(), teleop=MockTeleoperator(dof=2),
        mapper=IdentityMapper(), cameras=cm, mode=SessionMode.TELEOP, fps=30,
        error_bus=bus, resolved_config={},
    )
    await sm.start()
    assert sm.state == SessionState.READY
    assert sm.session.mode == SessionMode.TELEOP
    await sm.end()
