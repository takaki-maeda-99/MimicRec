from __future__ import annotations
import asyncio
from pathlib import Path

from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.adapters.mock_teleop import MockTeleoperator
from mimicrec.cameras.manager import CameraManager
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.lifecycle import SessionManager
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.types import SessionMode
from mimicrec.util.error_bus import ErrorBus


async def test_exit_criterion_3_control_loop_ticks_at_configured_fps(tmp_path: Path):
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
    await sm.episode_start()
    await asyncio.sleep(0.5)
    await sm.episode_stop()
    rows = sm._metrics.get("writer_rows_written")
    assert rows >= 10, f"expected >=10 rows in 0.5s at 30fps, got {rows}"
    await sm.episode_discard()
    await sm.end()
