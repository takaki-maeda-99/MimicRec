import asyncio

import numpy as np
import pyarrow.parquet as pq
import pytest

from mimicrec.motion.runtime import MotionGroup, MotionRuntime
from mimicrec.motion.se3 import SE3Delta
from mimicrec.motion.types import (
    JointPositionCommand,
    JointResourceState,
    MotionStep,
)
from mimicrec.recording.dataset_layout import dataset_paths, init_motion_dataset
from mimicrec.datasets.reader import load_motion_replay_trajectory
from mimicrec.session.motion_lifecycle import MotionSessionManager
from mimicrec.util.latest_value import LatestValue


class _Adapter:
    name = "fake"
    resource_names = ("arm",)

    def __init__(self):
        self.sent = []

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def safe_stop(self):
        pass

    async def read_resources(self):
        return {
            "arm": JointResourceState(
                position=np.zeros(2),
                velocity=np.zeros(2),
                effort=np.zeros(2),
                joint_names=("j1", "j2"),
            )
        }

    async def send_commands(self, commands):
        self.sent.append(dict(commands))


class _Mapper:
    def map(self, step, states):
        return {
            "robot.arm": JointPositionCommand(
                np.array([step.delta.tangent[0], 0])
            )
        }


class _Router:
    name = "test_router"

    def __init__(self):
        self.stop_count = 0
        self.release_count = 0
        self.channels = {"test": self}

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    def stop_motion(self):
        self.stop_count += 1

    def require_pose_release(self):
        self.release_count += 1


class _Cameras:
    _cameras = {}

    async def start(self):
        pass

    async def stop(self):
        pass


@pytest.mark.asyncio
async def test_motion_session_records_se3_and_namespaced_resource_command(tmp_path):
    dataset = tmp_path / "motion"
    init_motion_dataset(
        dataset,
        50,
        resources={
            "robot.arm": {"kind": "joint", "joint_names": ["j1", "j2"]}
        },
        motion_groups={"hand": {"auxiliary": []}},
        camera_names=[],
        profile_name="test",
    )
    slot = LatestValue()
    adapter = _Adapter()
    runtime = MotionRuntime(
        adapters={"robot": adapter},
        motion_groups=[MotionGroup(
            name="hand",
            input_slot=slot,
            mapper=_Mapper(),
            output_resources=("robot.arm",),
            control_rate_hz=100,
        )],
        state_rate_hz=100,
    )
    manager = MotionSessionManager(
        dataset_root=dataset,
        runtime=runtime,
        teleop_router=_Router(),
        cameras=_Cameras(),
        fps=50,
        task="move",
        instruction="move right",
        profile_name="test",
        resolved_config={},
        ds_name="motion",
    )
    await manager.start()
    try:
        await manager.episode_start()
        slot.set(
            MotionStep(
                SE3Delta(np.array([0.02, 0, 0, 0, 0, 0]), duration_sec=0.02),
                t_mono_ns=123,
            ),
            t_mono_ns=123,
        )
        for _ in range(100):
            if adapter.sent and manager._recorder_queue.qsize() > 0:
                break
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.05)
        await manager.episode_stop()
        await manager.episode_save(success=True)
    finally:
        await manager.end()

    parquet = dataset_paths(dataset).episode_parquet(0, 0)
    table = pq.read_table(parquet)
    assert table.num_rows > 0
    assert "action.motion.hand.se3_delta" in table.column_names
    assert "action.resource.robot.arm.joint_pos" in table.column_names
    assert table["action.motion.hand.se3_delta"][0].as_py()[0] == pytest.approx(0.02)
    replay = load_motion_replay_trajectory(dataset, 0)
    assert replay.frames
    assert replay.frames[0]["hand"].delta.tangent[0] == pytest.approx(0.02)


@pytest.mark.asyncio
async def test_motion_home_ramps_only_explicitly_calibrated_adapter(tmp_path):
    slot = LatestValue()
    adapter = _Adapter()
    runtime = MotionRuntime(
        adapters={"robot": adapter},
        motion_groups=[MotionGroup(
            name="hand",
            input_slot=slot,
            mapper=_Mapper(),
            output_resources=("robot.arm",),
            control_rate_hz=100,
        )],
        state_rate_hz=200,
    )
    router = _Router()
    manager = MotionSessionManager(
        dataset_root=tmp_path,
        runtime=runtime,
        teleop_router=router,
        cameras=_Cameras(),
        fps=50,
        task="home",
        instruction="",
        profile_name="test",
        resolved_config={},
        home_config={
            "duration_sec": 0.001,
            "fps": 1000,
            "hold_sec": 0,
            "adapters": {
                "robot": {
                    "joint_names": ["j1", "j2"],
                    "joint_pos": [0.4, -0.2],
                }
            },
        },
    )
    await manager.start()
    try:
        for _ in range(100):
            if runtime.snapshot_states():
                break
            await asyncio.sleep(0.002)
        await manager.return_home()
    finally:
        await manager.end()

    arm_batches = [batch["arm"] for batch in adapter.sent if "arm" in batch]
    assert arm_batches
    assert arm_batches[-1].position == pytest.approx([0.4, -0.2])
    assert router.stop_count >= 2
    assert router.release_count >= 1


@pytest.mark.asyncio
async def test_motion_inference_error_rearms_live_input(tmp_path):
    adapter = _Adapter()
    runtime = MotionRuntime(adapters={"robot": adapter}, motion_groups=[])
    router = _Router()
    manager = MotionSessionManager(
        dataset_root=tmp_path,
        runtime=runtime,
        teleop_router=router,
        cameras=_Cameras(),
        fps=50,
        task="inference",
        instruction="",
        profile_name="test",
        resolved_config={},
    )
    manager.session.mode = manager.session.mode.INFERENCE

    async def fail(**_kwargs):
        raise RuntimeError("model unavailable")

    task = asyncio.create_task(manager._run_motion_inference_and_rearm(fail))
    manager._inference_task = task
    await task

    assert manager._inference_task is None
    assert manager.session.mode == manager.session.mode.TELEOP
    assert router.stop_count == 1
    assert router.release_count == 1


@pytest.mark.asyncio
async def test_motion_home_is_blocked_while_estop_is_latched(tmp_path):
    runtime = MotionRuntime(adapters={"robot": _Adapter()}, motion_groups=[])
    manager = MotionSessionManager(
        dataset_root=tmp_path,
        runtime=runtime,
        teleop_router=_Router(),
        cameras=_Cameras(),
        fps=50,
        task="home",
        instruction="",
        profile_name="test",
        resolved_config={},
        home_config={"adapters": {"robot": {"joint_pos": [0, 0]}}},
    )
    manager.session.state = manager.session.state.READY
    manager._estop_latched = True

    with pytest.raises(Exception, match="E-stop is latched"):
        await manager.return_home()
