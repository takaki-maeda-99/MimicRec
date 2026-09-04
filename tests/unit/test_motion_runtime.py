import asyncio

import numpy as np
import pytest

from mimicrec.motion.runtime import MotionGroup, MotionRuntime
from mimicrec.motion.se3 import SE3Delta
from mimicrec.motion.types import (
    JointPositionCommand,
    JointResourceState,
    MotionStep,
)
from mimicrec.util.latest_value import LatestValue


class _Adapter:
    def __init__(self, name="robot", resources=("arm",)):
        self.name = name
        self.resource_names = resources
        self.connected = False
        self.activated = False
        self.disconnected = False
        self.safe_stopped = False
        self.sent = []

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.disconnected = True

    async def activate(self):
        self.activated = True

    async def safe_stop(self):
        self.safe_stopped = True

    async def read_resources(self):
        return {
            name: JointResourceState(
                position=np.zeros(1),
                velocity=np.zeros(1),
                effort=np.zeros(1),
                joint_names=(name,),
            )
            for name in self.resource_names
        }

    async def send_commands(self, commands):
        self.sent.append(dict(commands))


class _Mapper:
    def __init__(self, output):
        self.output = output

    def map(self, step, resource_states):
        assert isinstance(step, MotionStep)
        assert self.output in resource_states
        return {
            self.output: JointPositionCommand(
                np.array([step.delta.tangent[0]], dtype=np.float32)
            )
        }


def _group(name, output, slot=None):
    return MotionGroup(
        name=name,
        input_slot=slot or LatestValue(),
        mapper=_Mapper(output),
        output_resources=(output,),
        control_rate_hz=200,
    )


def test_runtime_rejects_resource_conflicts_before_connect():
    adapter = _Adapter()

    with pytest.raises(ValueError, match="claimed by both"):
        MotionRuntime(
            adapters={"right": adapter},
            motion_groups=[
                _group("teleop", "right.arm"),
                _group("whole_body", "right.arm"),
            ],
        )

    assert adapter.connected is False


def test_runtime_rejects_unknown_mapper_output_resource():
    with pytest.raises(ValueError, match="unknown resource"):
        MotionRuntime(
            adapters={"right": _Adapter()},
            motion_groups=[_group("bad", "missing.arm")],
        )


@pytest.mark.asyncio
async def test_runtime_reads_maps_and_dispatches_named_resource():
    adapter = _Adapter(resources=("arm", "gripper"))
    slot = LatestValue()
    runtime = MotionRuntime(
        adapters={"left": adapter},
        motion_groups=[_group("left_hand", "left.arm", slot)],
        state_rate_hz=200,
    )
    await runtime.start()
    assert adapter.activated
    try:
        for _ in range(100):
            if runtime.state("left.arm").peek() is not None:
                break
            await asyncio.sleep(0.002)
        slot.set(
            MotionStep(SE3Delta(np.array([0.25, 0, 0, 0, 0, 0]))),
            t_mono_ns=1,
        )
        for _ in range(100):
            if adapter.sent:
                break
            await asyncio.sleep(0.002)
        assert adapter.sent
        assert adapter.sent[-1]["arm"].position == pytest.approx([0.25])
        assert "left.gripper" in runtime.resource_names
    finally:
        await runtime.stop()

    assert adapter.safe_stopped
    assert adapter.disconnected


@pytest.mark.asyncio
async def test_connect_failure_rolls_back_other_adapters():
    good = _Adapter("good")
    bad = _Adapter("bad")

    async def fail():
        raise RuntimeError("no device")

    bad.connect = fail
    runtime = MotionRuntime(
        adapters={"good": good, "bad": bad},
        motion_groups=[],
    )

    with pytest.raises(RuntimeError, match="no device"):
        await runtime.start()

    assert good.disconnected
    assert good.safe_stopped


@pytest.mark.asyncio
async def test_activation_failure_safe_stops_and_disconnects_every_adapter():
    good = _Adapter("good")
    bad = _Adapter("bad")

    async def fail_activation():
        raise RuntimeError("cannot enable torque")

    bad.activate = fail_activation
    runtime = MotionRuntime(
        adapters={"good": good, "bad": bad},
        motion_groups=[],
    )

    with pytest.raises(RuntimeError, match="cannot enable torque"):
        await runtime.start()

    assert good.safe_stopped
    assert bad.safe_stopped
    assert good.disconnected
    assert bad.disconnected
