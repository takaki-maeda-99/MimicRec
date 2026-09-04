import asyncio

import pytest

from mimicrec.adapters.web_teleop import QuestRosTeleoperator
from mimicrec.motion.input import MotionTeleopRouter


@pytest.mark.asyncio
async def test_router_sends_messages_to_named_controller_channel():
    right = QuestRosTeleoperator()
    left = QuestRosTeleoperator()
    router = MotionTeleopRouter(
        {"right": right, "left": left}, default_channel="right"
    )
    await router.connect()
    try:
        await router.input_queue.put({"channel": "left", "cmd": "stop"})
        await router.input_queue.join()
        assert left.input_queue.qsize() == 1
        assert right.input_queue.qsize() == 0

        await router.input_queue.put({"cmd": "stop"})
        await router.input_queue.join()
        assert right.input_queue.qsize() == 1

        await router.input_queue.put({"channel": "left", "cmd": "home"})
        await router.input_queue.join()
        assert await router.home_requests.get() == "left"
        router.home_requests.task_done()
    finally:
        await router.disconnect()


@pytest.mark.asyncio
async def test_router_disconnect_releases_every_channel():
    right = QuestRosTeleoperator()
    left = QuestRosTeleoperator()
    right._ee_pose_active = True
    left._ee_pose_active = True
    router = MotionTeleopRouter(
        {"right": right, "left": left}, default_channel="right"
    )
    await router.connect()

    await router.disconnect()

    assert right._ee_pose_active is False
    assert left._ee_pose_active is False
