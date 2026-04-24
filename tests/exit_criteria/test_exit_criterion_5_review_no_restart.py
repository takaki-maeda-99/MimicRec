from __future__ import annotations
import asyncio
from pathlib import Path

from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.adapters.mock_teleop import MockTeleoperator
from mimicrec.cameras.manager import CameraManager
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.lifecycle import SessionManager
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.types import SessionMode, SessionState
from mimicrec.util.error_bus import ErrorBus


async def test_exit_criterion_5_review_does_not_restart_tasks(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=[])
    bus = ErrorBus()
    cm = CameraManager(cameras={}, error_bus=bus)
    sm = SessionManager(
        dataset_root=ds, robot=MockRobotAdapter(), teleop=MockTeleoperator(dof=2),
        mapper=IdentityMapper(), cameras=cm, mode=SessionMode.TELEOP, fps=30,
        error_bus=bus, resolved_config={},
    )
    await sm.start()
    loop_id_before = id(sm._control_loop_task)
    await sm.episode_start()
    await asyncio.sleep(0.1)
    await sm.episode_stop()
    assert sm.state == SessionState.REVIEW
    loop_id_after = id(sm._control_loop_task)
    assert loop_id_before == loop_id_after, "control loop task must not restart on REVIEW"
    await sm.episode_discard()
    await sm.end()
