from __future__ import annotations
import asyncio
from pathlib import Path

import numpy as np

from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.adapters.mock_teleop import MockTeleoperator
from mimicrec.cameras.manager import CameraManager
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.lifecycle import SessionManager
from mimicrec.session.replay import ReplayTrajectory
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.types import SessionMode
from mimicrec.util.error_bus import ErrorBus


async def test_exit_criterion_7_replay_gates_teleop_commands(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=[])
    bus = ErrorBus()
    cm = CameraManager(cameras={}, error_bus=bus)
    robot = MockRobotAdapter()
    teleop = MockTeleoperator(dof=2)
    sm = SessionManager(
        dataset_root=ds, robot=robot, teleop=teleop,
        mapper=IdentityMapper(), cameras=cm, mode=SessionMode.TELEOP, fps=30,
        error_bus=bus, resolved_config={},
    )
    await sm.start()
    await asyncio.sleep(0.1)
    # Set teleop to a "leaked" value
    teleop.target = np.array([99.0, 99.0], dtype=np.float32)
    robot.sent_commands.clear()

    traj = ReplayTrajectory(joint_targets=np.array([[-1.0, -1.0]] * 30, dtype=np.float32))
    await sm.replay_start(traj)
    await asyncio.sleep(0.5)
    # Check that 99.0 never appeared in sent commands during replay
    for cmd in robot.sent_commands:
        assert not np.allclose(cmd, [99.0, 99.0]), "teleop leaked into commands during replay"
    await sm.end()
