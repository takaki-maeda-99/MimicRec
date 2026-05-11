"""idle 復帰のモード別挙動。

- HAND_TEACH: セッション開始時もエピソード間も発火 (after_mode=GRAVITY_COMP)
- TELEOP: 常にスキップ (リーダー追従中に snap するため)
- INFERENCE: 常にスキップ
"""
from __future__ import annotations
from unittest.mock import AsyncMock, patch

import pytest

from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.adapters.mock_teleop import MockTeleoperator
from mimicrec.adapters.robot import RobotMode
from mimicrec.cameras.mock_camera import MockCamera
from mimicrec.cameras.manager import CameraManager
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.lifecycle import SessionManager
from mimicrec.types import SessionMode
from mimicrec.util.error_bus import ErrorBus


def _build_sm(mode: SessionMode, dataset_root) -> SessionManager:
    bus = ErrorBus()
    return SessionManager(
        dataset_root=dataset_root,
        robot=MockRobotAdapter(),
        teleop=MockTeleoperator(dof=2),
        mapper=IdentityMapper(),
        cameras=CameraManager(cameras={"front": MockCamera("front")}, error_bus=bus),
        mode=mode,
        fps=30,
        error_bus=bus,
        resolved_config={},
        replay_safety=None,
    )


@pytest.mark.asyncio
async def test_teleop_skips_move_to_idle(tmp_path):
    sm = _build_sm(SessionMode.TELEOP, tmp_path)
    with patch("mimicrec.session.lifecycle.move_to_idle", new=AsyncMock()) as m:
        await sm._move_to_idle_for_session()
    m.assert_not_called()


@pytest.mark.asyncio
async def test_hand_teach_calls_move_to_idle_with_gravity_comp(tmp_path):
    sm = _build_sm(SessionMode.HAND_TEACH, tmp_path)
    with patch("mimicrec.session.lifecycle.move_to_idle", new=AsyncMock()) as m:
        await sm._move_to_idle_for_session()
    m.assert_called_once()
    assert m.call_args.kwargs["after_mode"] == RobotMode.GRAVITY_COMP


@pytest.mark.asyncio
async def test_inference_still_skips_move_to_idle(tmp_path):
    sm = _build_sm(SessionMode.INFERENCE, tmp_path)
    with patch("mimicrec.session.lifecycle.move_to_idle", new=AsyncMock()) as m:
        await sm._move_to_idle_for_session()
    m.assert_not_called()
