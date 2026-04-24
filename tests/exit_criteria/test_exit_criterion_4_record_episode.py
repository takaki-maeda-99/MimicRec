from __future__ import annotations
import asyncio
from pathlib import Path

import pyarrow.parquet as pq

from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.adapters.mock_teleop import MockTeleoperator
from mimicrec.cameras.manager import CameraManager
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.lifecycle import SessionManager
from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.types import SessionMode
from mimicrec.util.error_bus import ErrorBus


async def test_exit_criterion_4_record_and_persist_episode(tmp_path: Path):
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
    await asyncio.sleep(0.2)
    await sm.episode_stop()
    await sm.episode_save(success=True, comment="test")
    paths = dataset_paths(ds)
    pq_path = paths.data_dir / "chunk-000" / "episode_000000.parquet"
    assert pq_path.exists()
    table = pq.read_table(pq_path)
    assert table.num_rows >= 3
    await sm.end()
