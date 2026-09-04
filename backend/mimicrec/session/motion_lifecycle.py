"""Session lifecycle for namespaced multi-adapter MotionRuntime profiles."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import time

import numpy as np
from scipy.spatial.transform import Rotation

from mimicrec.errors import InvalidTransitionError
from mimicrec.motion.runtime import MotionRuntime
from mimicrec.motion.types import (
    JointResourceState,
    JointPositionCommand,
    MotionSampleBundle,
    ResourceCommand,
    ResourceState,
    ScalarResourceState,
    ScalarPositionCommand,
)
from mimicrec.recording.metadata import read_episodes, upsert_task
from mimicrec.recording.motion_writer import run_motion_writer
from mimicrec.recording.pending import PendingEpisode
from mimicrec.session.state import Session
from mimicrec.types import RobotState, SessionMode, SessionState, Stamped
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics


logger = logging.getLogger(__name__)


class _MotionRobotFacade:
    """Small compatibility surface for state WebSockets and emergency stop."""

    def __init__(self, runtime: MotionRuntime) -> None:
        self.runtime = runtime
        self.name = "motion_graph"
        self.joint_names: list[str] = []
        self.dof = 0

    def update_layout(self, states: dict[str, ResourceState]) -> None:
        names: list[str] = []
        for resource in self.runtime.resource_names:
            state = states.get(resource)
            if isinstance(state, JointResourceState):
                names.extend(f"{resource}.{name}" for name in state.joint_names)
        self.joint_names = names
        self.dof = len(names)

    async def estop(self) -> dict:
        results = await asyncio.gather(
            *(self._stop_adapter(adapter) for adapter in self.runtime.adapters.values()),
            return_exceptions=True,
        )
        errors = [str(result) for result in results if isinstance(result, Exception)]
        return {"ok": not errors, "errors": errors}

    async def clear_estop(self) -> dict:
        results = await asyncio.gather(
            *(self._clear_adapter(adapter) for adapter in self.runtime.adapters.values()),
            return_exceptions=True,
        )
        errors = [str(result) for result in results if isinstance(result, Exception)]
        return {"ok": not errors, "errors": errors}

    @staticmethod
    async def _stop_adapter(adapter) -> None:
        estop = getattr(adapter, "estop", None)
        if estop is not None:
            await estop()
        else:
            await adapter.safe_stop()

    @staticmethod
    async def _clear_adapter(adapter) -> None:
        clear = getattr(adapter, "clear_estop", None)
        if clear is None:
            raise RuntimeError(f"adapter {adapter.name!r} cannot clear E-stop")
        result = await clear()
        if isinstance(result, dict) and not result.get("ok", False):
            raise RuntimeError(str(result))


class MotionSessionManager:
    """Record synchronized SE3Delta streams and multiple hardware resources."""

    def __init__(
        self,
        *,
        dataset_root,
        runtime: MotionRuntime,
        teleop_router,
        cameras,
        fps: int,
        task: str,
        instruction: str,
        profile_name: str,
        resolved_config: dict,
        home_config: dict | None = None,
        coordinator=None,
        ds_name: str | None = None,
        app=None,
    ) -> None:
        self._dataset_root = dataset_root
        self._motion_runtime = runtime
        self._teleop = teleop_router
        self._cameras = cameras
        self._fps = int(fps)
        self._task = task or "default"
        self._instruction = instruction or ""
        self._profile_name = profile_name
        self._home_config = dict(home_config or {})
        self._resolved_config = resolved_config
        self._coordinator = coordinator
        self._ds_name = ds_name
        self._app = app
        self._app_loop = asyncio.get_running_loop()
        self.session = Session(mode=SessionMode.TELEOP, state=SessionState.IDLE)
        self._metrics = Metrics()
        self._robot = _MotionRobotFacade(runtime)
        self._robot_state_slot: LatestValue[RobotState] = LatestValue()
        self._resource_state_slots = {
            name: runtime.state(name) for name in runtime.resource_names
        }
        self._current_pending: LatestValue = LatestValue()
        self._recorder_queue: asyncio.Queue = asyncio.Queue(maxsize=max(30, fps * 5))
        self._writer_task: asyncio.Task | None = None
        self._replay_task: asyncio.Task | None = None
        self._inference_task: asyncio.Task | None = None
        self._home_request_task: asyncio.Task | None = None
        self._pending: PendingEpisode | None = None
        self._episode_index = 0
        self._episode_start_t_mono_ns: int | None = None
        self._episode_stop_t_mono_ns: int | None = None
        self._estop_latched = False
        self._fk = None
        self._instruction_slot: LatestValue[str] = LatestValue()
        self._instruction_slot.set(self._instruction, t_mono_ns=time.monotonic_ns())
        self._chunk_buffer = None
        self._inference_config_name: str | None = None
        self.inference_hub = None
        runtime.snapshot_rate_hz = float(fps)
        runtime.on_snapshot = self._on_snapshot

    def _on_snapshot(
        self,
        tick_t_mono_ns: int,
        states: dict[str, ResourceState],
        commands: dict[str, ResourceCommand],
        steps: dict,
    ) -> None:
        mapper_telemetry: dict[str, dict[str, float]] = {}
        for group in self._motion_runtime.motion_groups:
            telemetry = getattr(group.mapper, "telemetry", None)
            if telemetry is None:
                continue
            try:
                values = telemetry()
            except TypeError:
                # Some legacy mapper telemetry needs legacy state/command
                # arguments and is already reported by its control loop.
                continue
            mapper_telemetry[group.name] = {
                str(name): float(value) for name, value in values.items()
            }
            for name, value in values.items():
                self._metrics.set_gauge(
                    f"motion_{group.name}_{name}", float(value)
                )
        self._robot.update_layout(states)
        positions: list[np.ndarray] = []
        velocities: list[np.ndarray] = []
        efforts: list[np.ndarray] = []
        for resource in self._motion_runtime.resource_names:
            state = states.get(resource)
            if isinstance(state, JointResourceState):
                positions.append(state.position)
                velocities.append(state.velocity)
                efforts.append(state.effort)
        if positions:
            legacy_state = RobotState(
                joint_pos=np.concatenate(positions).astype(np.float32),
                joint_vel=np.concatenate(velocities).astype(np.float32),
                joint_effort=np.concatenate(efforts).astype(np.float32),
                t_mono_ns=tick_t_mono_ns,
            )
            self._robot_state_slot.set(legacy_state, t_mono_ns=tick_t_mono_ns)

        if self.session.state != SessionState.RECORDING:
            return
        required_groups = {
            group.name for group in self._motion_runtime.motion_groups
        }
        required_commands = {
            resource
            for group in self._motion_runtime.motion_groups
            for resource in group.output_resources
        }
        # A parquet schema is inferred from the first row. Do not let an
        # adapter-read snapshot race ahead of initial controller commands and
        # permanently omit the SE3Delta/action columns from that episode.
        if not required_groups.issubset(steps):
            return
        if not required_commands.issubset(commands):
            return
        frames = {
            name: self._cameras.latest(name).peek()
            for name in self._cameras._cameras
        }
        bundle = MotionSampleBundle(
            tick_t_mono_ns=tick_t_mono_ns,
            states=dict(states),
            commands=dict(commands),
            motion_steps=dict(steps),
            frames=frames,
            mapper_telemetry=mapper_telemetry,
        )
        try:
            self._recorder_queue.put_nowait(bundle)
        except asyncio.QueueFull:
            self._metrics.inc("recorder_queue_dropped")

    async def start(self) -> None:
        if self.session.state != SessionState.IDLE:
            raise InvalidTransitionError("motion session is already started")
        existing = list(read_episodes(self._dataset_root / "meta", include_deleted=True))
        if existing:
            self._episode_index = max(int(row["episode_index"]) for row in existing) + 1
        self.session.stopped.clear()
        try:
            await self._teleop.connect()
            await self._cameras.start()
            await self._motion_runtime.start()
        except Exception:
            await self._motion_runtime.stop()
            await self._cameras.stop()
            await self._teleop.disconnect()
            raise
        self._writer_task = asyncio.create_task(
            run_motion_writer(
                current_pending=self._current_pending,
                queue=self._recorder_queue,
                metrics=self._metrics,
                stopped=self.session.stopped,
            ),
            name="motion-writer",
        )
        if hasattr(self._teleop, "home_requests"):
            self._home_request_task = asyncio.create_task(
                self._run_home_requests(), name="motion-home-requests"
            )
        self.session.state = SessionState.READY

    async def _run_home_requests(self) -> None:
        while not self.session.stopped.is_set():
            channel = await self._teleop.home_requests.get()
            try:
                await self.return_home(channel=channel)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("motion home request failed: %s", exc)
                await self._motion_runtime.error_bus.publish(exc)
            finally:
                self._teleop.home_requests.task_done()

    async def episode_start(self) -> None:
        if self.session.state != SessionState.READY:
            raise InvalidTransitionError(
                f"episode_start requires READY, got {self.session.state}"
            )
        self._pending = PendingEpisode.open(
            self._dataset_root,
            self._episode_index,
            coordinator=self._coordinator,
            ds_name=self._ds_name,
            app_loop=self._app_loop,
            app=self._app,
        )
        camera_sizes: dict[str, tuple[int, int]] = {}
        for name in self._cameras._cameras:
            stamped = self._cameras.latest(name).peek()
            if stamped is not None:
                height, width = stamped.value.image.shape[:2]
                camera_sizes[name] = (width, height)
        if camera_sizes:
            self._pending.open_video_writers(self._fps, camera_sizes)
        now = time.monotonic_ns()
        self._episode_start_t_mono_ns = now
        self._episode_stop_t_mono_ns = None
        self._current_pending.set(self._pending, t_mono_ns=now)
        self.session.state = SessionState.RECORDING
        if self.session.mode == SessionMode.INFERENCE:
            stamped = self._instruction_slot.peek()
            self.session.locked_instruction = stamped.value if stamped else self._instruction

    async def episode_stop(self, *, stop_reason: str = "manual") -> None:
        if self.session.state != SessionState.RECORDING:
            raise InvalidTransitionError(
                f"episode_stop requires RECORDING, got {self.session.state}"
            )
        self._episode_stop_t_mono_ns = time.monotonic_ns()
        self.session.state = SessionState.REVIEW
        if self.session.mode == SessionMode.INFERENCE:
            self.session.producer_paused = True
        await asyncio.wait_for(self._recorder_queue.join(), timeout=60.0)
        self._current_pending.set(None, t_mono_ns=time.monotonic_ns())
        if self._pending is not None:
            self._pending.finalize()

    async def episode_save(
        self, success: bool | None = None, comment: str | None = None
    ) -> None:
        if self.session.state != SessionState.REVIEW:
            raise InvalidTransitionError(
                f"episode_save requires REVIEW, got {self.session.state}"
            )
        if self._pending is not None:
            upsert_task(
                self._dataset_root / "meta",
                self._task,
                self.session.locked_instruction or self._instruction,
            )
            stop = self._episode_stop_t_mono_ns or time.monotonic_ns()
            start = self._episode_start_t_mono_ns or stop
            self._pending.save(metadata_extra={
                "episode_index": self._episode_index,
                "task": self._task,
                "instruction": self.session.locked_instruction or self._instruction,
                "robot": "motion_graph",
                "teleop": self._teleop.name,
                "mapper": self._profile_name,
                "cameras": list(self._cameras._cameras),
                "mode": self.session.mode.value,
                "fps": self._fps,
                "success": success,
                "comment": comment,
                "start_t_mono_ns": start,
                "end_t_mono_ns": stop,
                "duration_sec": (stop - start) / 1e9,
                "num_frames": self._pending.num_frames,
                "resolved_config": self._resolved_config,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            })
            self._pending = None
            self._episode_index += 1
        self.session.state = SessionState.READY
        if self.session.mode == SessionMode.INFERENCE:
            self.session.locked_instruction = None
            self.session.producer_paused = False

    async def episode_discard(self) -> None:
        if self.session.state != SessionState.REVIEW:
            raise InvalidTransitionError(
                f"episode_discard requires REVIEW, got {self.session.state}"
            )
        if self._pending is not None:
            self._pending.discard()
            self._pending = None
        self.session.state = SessionState.READY
        if self.session.mode == SessionMode.INFERENCE:
            self.session.locked_instruction = None
            self.session.producer_paused = False

    async def return_home(self, *, channel: str | None = None) -> None:
        if self.session.state != SessionState.READY:
            raise InvalidTransitionError("home requires a READY motion session")
        if self.session.replay_active or self._inference_task is not None:
            raise InvalidTransitionError("home is blocked during replay or inference")
        if self._estop_latched:
            raise InvalidTransitionError("home is blocked while E-stop is latched")
        targets = dict(self._home_config.get("adapters") or {})
        if channel is not None:
            targets = {
                adapter_id: target
                for adapter_id, target in targets.items()
                if channel in tuple(target.get("channels") or ())
            }
        if not targets:
            raise InvalidTransitionError(
                "this motion profile has no calibrated home targets"
                + (f" for channel {channel!r}" if channel is not None else "")
            )
        if self.session.home_active:
            raise InvalidTransitionError("home move is already active")
        duration = float(self._home_config.get("duration_sec", 2.0))
        fps = int(self._home_config.get("fps", 30))
        hold = float(self._home_config.get("hold_sec", 0.3))
        if duration <= 0 or fps <= 0 or hold < 0:
            raise ValueError("invalid motion profile home timing")

        self.session.home_active = True
        self._motion_runtime.pause_inputs()
        self._teleop.stop_motion()
        try:
            # Let the final controller tick and adapter dispatch finish before
            # direct, adapter-scoped home commands take ownership.
            await asyncio.sleep(max(0.05, 2.0 / fps))
            states = self._motion_runtime.snapshot_states()
            starts: dict[str, tuple[np.ndarray, float | None, dict]] = {}
            for adapter_id, target in targets.items():
                arm_name = f"{adapter_id}.arm"
                arm = states.get(arm_name)
                if not isinstance(arm, JointResourceState):
                    raise InvalidTransitionError(
                        f"home state unavailable for {arm_name!r}"
                    )
                goal = np.asarray(target["joint_pos"], dtype=np.float32)
                if goal.shape != arm.position.shape or not np.isfinite(goal).all():
                    raise ValueError(
                        f"home target shape for {arm_name!r} is {goal.shape}; "
                        f"expected {arm.position.shape}"
                    )
                names = tuple(str(name) for name in target.get("joint_names") or ())
                if names and names != arm.joint_names:
                    raise ValueError(
                        f"home joint names for {arm_name!r} do not match adapter"
                    )
                gripper = states.get(f"{adapter_id}.gripper")
                gripper_start = (
                    gripper.position
                    if isinstance(gripper, ScalarResourceState)
                    else None
                )
                starts[str(adapter_id)] = (arm.position.copy(), gripper_start, target)

            n_steps = max(1, int(round(duration * fps)))
            interval = 1.0 / fps
            for index in range(1, n_steps + 1):
                progress = index / n_steps
                # Zero velocity and acceleration at both ends prevents the
                # home move itself from kicking a gravity-loaded joint.
                alpha = (
                    10.0 * progress**3
                    - 15.0 * progress**4
                    + 6.0 * progress**5
                )
                await self._send_home_commands(starts, alpha)
                await asyncio.sleep(interval)
            for _ in range(int(round(hold * fps))):
                await self._send_home_commands(starts, 1.0)
                await asyncio.sleep(interval)
            for group in self._motion_runtime.motion_groups:
                reset = getattr(group.mapper, "reset", None)
                if reset is not None:
                    reset()
        finally:
            self._teleop.stop_motion()
            self._require_input_release()
            self._motion_runtime.resume_inputs()
            self.session.home_active = False

    async def _send_home_commands(
        self,
        starts: dict[str, tuple[np.ndarray, float | None, dict]],
        alpha: float,
    ) -> None:
        now = time.monotonic_ns()
        await asyncio.gather(*(
            self._send_adapter_home(adapter_id, start, gripper, target, alpha, now)
            for adapter_id, (start, gripper, target) in starts.items()
        ))

    async def _send_adapter_home(
        self,
        adapter_id: str,
        start: np.ndarray,
        gripper_start: float | None,
        target: dict,
        alpha: float,
        now: int,
    ) -> None:
        goal = np.asarray(target["joint_pos"], dtype=np.float32)
        commands: dict[str, ResourceCommand] = {
            "arm": JointPositionCommand(start + (goal - start) * alpha, now)
        }
        gripper_goal = target.get("gripper_pos")
        if gripper_start is not None and gripper_goal is not None:
            commands["gripper"] = ScalarPositionCommand(
                gripper_start + (float(gripper_goal) - gripper_start) * alpha,
                now,
            )
        await self._motion_runtime.adapters[adapter_id].send_commands(commands)

    def _require_input_release(self) -> None:
        for channel in getattr(self._teleop, "channels", {}).values():
            require_release = getattr(channel, "require_pose_release", None)
            if require_release is not None:
                require_release()

    async def replay_start(self, trajectory) -> None:
        from mimicrec.session.motion_replay import (
            MotionReplayTrajectory,
            run_motion_replay,
        )
        if not isinstance(trajectory, MotionReplayTrajectory):
            raise InvalidTransitionError(
                "motion session requires an SE3Delta replay trajectory"
            )
        if self.session.state != SessionState.READY:
            raise InvalidTransitionError("motion replay requires READY")
        if self.session.replay_active:
            raise InvalidTransitionError("another replay is already active")
        if self._estop_latched:
            raise InvalidTransitionError("replay is blocked while E-stop is latched")
        self._teleop.stop_motion()
        self._replay_task = asyncio.create_task(
            self._run_motion_replay_and_rearm(run_motion_replay, trajectory),
            name="motion-replay",
        )

    async def _run_motion_replay_and_rearm(self, replay_fn, trajectory) -> None:
        try:
            await replay_fn(
                self.session,
                self._motion_runtime,
                trajectory,
                speed=float(getattr(trajectory, "speed", 1.0)),
            )
        finally:
            for channel in getattr(self._teleop, "channels", {}).values():
                require_release = getattr(channel, "require_pose_release", None)
                if require_release is not None:
                    require_release()

    async def replay_stop(self) -> None:
        self.session.replay_active = False
        if self._replay_task is not None:
            self._replay_task.cancel()
            try:
                await self._replay_task
            except (asyncio.CancelledError, Exception):
                pass
            self._replay_task = None
        for channel in getattr(self._teleop, "channels", {}).values():
            require_release = getattr(channel, "require_pose_release", None)
            if require_release is not None:
                require_release()

    def _inference_state_for_group(self, group) -> Stamped[RobotState] | None:
        arm_resource = next(
            (name for name in group.output_resources if name.endswith(".arm")),
            None,
        )
        if arm_resource is None:
            return None
        state = self._motion_runtime.snapshot_states().get(arm_resource)
        if not isinstance(state, JointResourceState):
            return None
        gripper_resource = next(
            (
                name
                for name in group.output_resources
                if name.endswith(".gripper")
            ),
            None,
        )
        gripper = self._motion_runtime.snapshot_states().get(gripper_resource)
        gripper_pos = (
            gripper.position if isinstance(gripper, ScalarResourceState) else None
        )
        transform = state.ee_transform
        if transform is None:
            mapper = group.mapper
            forward = getattr(mapper, "forward_kinematics", None)
            if forward is not None:
                transform = forward(state.position)
            else:
                legacy = getattr(mapper, "mapper", None)
                ik = getattr(legacy, "_rebotarm_ik", None)
                if ik is not None:
                    transform = ik.forward_kinematics(np.rad2deg(state.position))
        ee_pos = ee_rotvec = None
        if transform is not None:
            ee_pos = np.asarray(transform[:3, 3], dtype=np.float32)
            ee_rotvec = Rotation.from_matrix(transform[:3, :3]).as_rotvec().astype(
                np.float32
            )
        robot_state = RobotState(
            joint_pos=state.position.copy(),
            joint_vel=state.velocity.copy(),
            joint_effort=state.effort.copy(),
            t_mono_ns=state.t_mono_ns,
            ee_pos=ee_pos,
            ee_rotvec=ee_rotvec,
            gripper_pos=gripper_pos,
        )
        return Stamped(value=robot_state, t_mono_ns=state.t_mono_ns)

    async def start_inference_session(
        self,
        *,
        contract,
        instruction: str,
        inference_config_name: str,
    ) -> None:
        from mimicrec.inference.client import InferenceClient
        from mimicrec.inference.motion_decoder import MotionActionDecoder
        from mimicrec.inference.motion_loop import run_motion_inference

        if self.session.state != SessionState.READY:
            raise InvalidTransitionError("motion inference requires READY")
        if self._inference_task is not None:
            raise InvalidTransitionError("motion inference is already active")
        if self._estop_latched:
            raise InvalidTransitionError("inference is blocked while E-stop is latched")
        group_name = contract.motion_group
        if not group_name:
            if len(self._motion_runtime.motion_groups) != 1:
                raise InvalidTransitionError(
                    "inference contract must declare motion_group for a "
                    "multi-group profile"
                )
            group_name = self._motion_runtime.motion_groups[0].name
        group = next(
            (
                item
                for item in self._motion_runtime.motion_groups
                if item.name == group_name
            ),
            None,
        )
        if group is None:
            raise InvalidTransitionError(f"unknown inference motion_group {group_name!r}")
        arm_resource = next(
            (name for name in group.output_resources if name.endswith(".arm")),
            None,
        )
        if arm_resource is None:
            raise InvalidTransitionError("inference motion group has no arm resource")
        adapter_id = arm_resource.split(".", 1)[0]
        adapter = self._motion_runtime.adapters[adapter_id]
        declaration_source = getattr(adapter, "robot", adapter)
        gripper_convention = (
            declaration_source.default_gripper_convention()
            if hasattr(declaration_source, "default_gripper_convention")
            else None
        )
        proprio_layout = (
            declaration_source.proprio_layout()
            if hasattr(declaration_source, "proprio_layout")
            else None
        )
        client = InferenceClient(
            spec=contract,
            gripper_convention=gripper_convention,
            proprio_layout=proprio_layout,
        )
        decoder = MotionActionDecoder(
            contract,
            duration_sec=1.0 / self._fps,
            action_stats=contract.resolve_action_stats(),
        )
        self._instruction = instruction
        self._instruction_slot.set(instruction, t_mono_ns=time.monotonic_ns())
        self._inference_config_name = inference_config_name
        self.session.mode = SessionMode.INFERENCE
        self.session.producer_paused = False
        camera_slots = {
            name: self._cameras.latest(name) for name in self._cameras._cameras
        }
        publish = self.inference_hub.publish if self.inference_hub is not None else None
        self._inference_task = asyncio.create_task(
            self._run_motion_inference_and_rearm(
                run_motion_inference,
                session=self.session,
                runtime=self._motion_runtime,
                group_name=group_name,
                client=client,
                decoder=decoder,
                state_provider=lambda: self._inference_state_for_group(group),
                camera_slots=camera_slots,
                instruction_slot=self._instruction_slot,
                publish_event=publish,
            ),
            name=f"motion-inference:{group_name}",
        )

    async def _run_motion_inference_and_rearm(self, inference_fn, **kwargs) -> None:
        task = asyncio.current_task()
        try:
            await inference_fn(**kwargs)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("motion inference stopped after an error")
            await self._motion_runtime.error_bus.publish(exc)
            if self.inference_hub is not None:
                await self.inference_hub.publish({
                    "type": "error",
                    "error": type(exc).__name__,
                    "message": str(exc),
                })
        finally:
            self._motion_runtime.resume_inputs()
            self._teleop.stop_motion()
            self._require_input_release()
            if self._inference_task is task:
                self._inference_task = None
                self.session.mode = SessionMode.TELEOP
                self.session.producer_paused = False
                self._inference_config_name = None

    async def stop_inference_session(self) -> None:
        self.session.producer_paused = True
        task = self._inference_task
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            if self._inference_task is task:
                self._inference_task = None
        self._motion_runtime.resume_inputs()
        self._teleop.stop_motion()
        self._require_input_release()
        self.session.mode = SessionMode.TELEOP
        self.session.producer_paused = False
        self._inference_config_name = None

    def inference_state_snapshot(self) -> dict:
        return {
            "phase": self.session.state.value,
            "mode": self.session.mode.value,
            "config": self._inference_config_name,
            "instruction": self._instruction,
            "running": self._inference_task is not None
            and not self._inference_task.done(),
        }

    async def end(self) -> None:
        if self.session.state == SessionState.IDLE:
            return
        self.session.stopped.set()
        if self._home_request_task is not None:
            self._home_request_task.cancel()
            try:
                await self._home_request_task
            except (asyncio.CancelledError, Exception):
                pass
            self._home_request_task = None
        await self.replay_stop()
        await self.stop_inference_session()
        self._current_pending.set(None, t_mono_ns=time.monotonic_ns())
        if self._pending is not None:
            self._pending.discard()
            self._pending = None
        await self._motion_runtime.stop()
        await self._cameras.stop()
        await self._teleop.disconnect()
        if self._writer_task is not None:
            try:
                await asyncio.wait_for(self._writer_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._writer_task.cancel()
            self._writer_task = None
        self.session.state = SessionState.IDLE
