from __future__ import annotations
import asyncio
from pathlib import Path

from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.adapters.mock_teleop import MockTeleoperator
from mimicrec.cameras.manager import CameraManager
from mimicrec.datasets.reader import iter_episodes
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.lifecycle import SessionManager
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.metadata import tombstone_episode
from mimicrec.types import SessionMode
from mimicrec.util.error_bus import ErrorBus


async def test_exit_criterion_8_tombstone_delete(tmp_path: Path):
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
    await asyncio.sleep(0.1)
    await sm.episode_stop()
    await sm.episode_save()
    await sm.end()

    # Tombstone the episode
    tombstone_episode(ds / "meta", 0, deleted_at_unix=1700000000)
    live = list(iter_episodes(ds, include_deleted=False))
    assert len(live) == 0
    all_eps = list(iter_episodes(ds, include_deleted=True))
    assert len(all_eps) == 1 and all_eps[0]["deleted"] is True
