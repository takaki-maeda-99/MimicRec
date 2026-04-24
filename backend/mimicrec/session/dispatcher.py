from __future__ import annotations
import asyncio

from mimicrec.errors import HardwareError
from mimicrec.types import RobotCommand
from mimicrec.util.error_bus import ErrorBus
from mimicrec.util.latest_value import LatestValue


async def run_command_dispatcher(
    robot,
    goal: LatestValue[RobotCommand],
    errors: ErrorBus,
    stopped: asyncio.Event,
) -> None:
    last_seen_seq = 0
    while not stopped.is_set():
        current = goal.peek()
        if current is None or goal.seq <= last_seen_seq:
            try:
                stamped = await asyncio.wait_for(
                    goal.wait_for_new(since_seq=last_seen_seq),
                    timeout=0.05,
                )
            except asyncio.TimeoutError:
                continue
            current = stamped
        last_seen_seq = goal.seq
        try:
            await robot.send_joint_command(current.value.q)
        except HardwareError as e:
            await errors.publish(e)
