from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from mimicrec.adapters.robot import RobotAdapter, RobotMode
from mimicrec.cameras.manager import CameraManager
from mimicrec.errors import HandTeachNotSupportedError, HardwareError, InvalidTransitionError
from mimicrec.recording.pending import PendingEpisode
from mimicrec.session.control_loop import run_handteach_control_loop, run_teleop_control_loop
from mimicrec.session.dispatcher import run_command_dispatcher
from mimicrec.session.replay_safety import ReplaySafetyConfig
from mimicrec.session.state import Session
from mimicrec.recording.writer import run_writer

logger = logging.getLogger(__name__)
from mimicrec.types import (
    RobotCommand, RobotState, SampleBundle, SessionMode, SessionState, TeleopAction,
)
from mimicrec.util.clock import RealClock
from mimicrec.util.error_bus import ErrorBus
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics


@dataclass
class StartSessionRequestDomain:
    """Plan-A internal request — Plan B maps HTTP bodies to this."""
    robot: RobotAdapter
    mode: SessionMode


def precheck_start(req: StartSessionRequestDomain) -> None:
    if req.mode == SessionMode.HAND_TEACH and not req.robot.supports_mode(RobotMode.GRAVITY_COMP):
        raise HandTeachNotSupportedError(
            f"robot {req.robot.name!r} does not support hand-teach "
            f"(GRAVITY_COMP). Start a TELEOP-mode session instead."
        )


def assert_can_start_episode(session: Session) -> None:
    if session.state != SessionState.READY:
        raise InvalidTransitionError(
            f"episode/start requires READY, got {session.state}"
        )
    if session.replay_active:
        raise InvalidTransitionError("episode/start blocked while replay is active")


class SessionManager:
    """Domain-level lifecycle: wires together all subsystems for one session."""

    def __init__(
        self,
        dataset_root: Path,
        robot,          # RobotAdapter
        teleop,         # Teleoperator | None (None for hand-teach)
        mapper,         # TeleopMapper | None
        cameras: CameraManager,
        mode: SessionMode,
        fps: int,
        error_bus: ErrorBus,
        resolved_config: dict,
        replay_safety: ReplaySafetyConfig | None = None,
        fk=None,  # FKService | None — adds EE columns to recordings when set
        task: str = "default",
        instruction: str = "",
    ):
        self.session = Session(mode=mode, state=SessionState.IDLE)
        self._dataset_root = dataset_root
        self._robot = robot
        self._teleop = teleop
        self._mapper = mapper
        self._cameras = cameras
        self._fps = fps
        self._error_bus = error_bus
        self._resolved_config = resolved_config
        self._replay_safety = replay_safety
        self._task = task
        self._instruction = instruction
        self._fk = fk
        self._metrics = Metrics()

        # Slots
        self._robot_state_slot: LatestValue[RobotState] = LatestValue()
        self._teleop_slot: LatestValue[TeleopAction] = LatestValue()
        self._command_goal_slot: LatestValue[RobotCommand] = LatestValue()
        self._current_pending: LatestValue[PendingEpisode | None] = LatestValue()
        self._recorder_queue: asyncio.Queue[SampleBundle] = asyncio.Queue()

        # Tasks
        self._robot_reader_task: asyncio.Task | None = None
        self._teleop_reader_task: asyncio.Task | None = None
        self._control_loop_task: asyncio.Task | None = None
        self._dispatcher_task: asyncio.Task | None = None
        self._writer_task: asyncio.Task | None = None
        self._replay_task: asyncio.Task | None = None
        self._error_handler_task: asyncio.Task | None = None

        # Episode tracking
        self._episode_index = 0
        self._pending: PendingEpisode | None = None
        self._episode_start_t_mono_ns: int | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> SessionState:
        return self.session.state

    # ------------------------------------------------------------------
    # Reader tasks
    # ------------------------------------------------------------------

    async def _run_robot_reader(self) -> None:
        consecutive_errors = 0
        while not self.session.stopped.is_set():
            try:
                t = time.monotonic_ns()
                state = await self._robot.read_state()
                state.t_mono_ns = t
                self._robot_state_slot.set(state, t_mono_ns=t)
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                # Log first occurrence and every 100th to avoid log flood
                if consecutive_errors == 1 or consecutive_errors % 100 == 0:
                    logger.warning(
                        "robot reader error (#%d): %s: %s",
                        consecutive_errors, type(e).__name__, e,
                    )
                await asyncio.sleep(0.01)

    async def _run_teleop_reader(self) -> None:
        consecutive_errors = 0
        while not self.session.stopped.is_set():
            try:
                t = time.monotonic_ns()
                action = await self._teleop.read_action()
                action.t_mono_ns = t
                self._teleop_slot.set(action, t_mono_ns=t)
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors == 1 or consecutive_errors % 100 == 0:
                    logger.warning(
                        "teleop reader error (#%d): %s: %s",
                        consecutive_errors, type(e).__name__, e,
                    )
                await asyncio.sleep(0.01)

    # ------------------------------------------------------------------
    # Error handler
    # ------------------------------------------------------------------

    async def _handle_errors(self) -> None:
        sub = self._error_bus.subscribe()
        while not self.session.stopped.is_set():
            try:
                evt = await asyncio.wait_for(sub.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            if isinstance(evt, HardwareError) and self.session.state == SessionState.RECORDING:
                # Auto-discard on hardware error during recording
                self.session.state = SessionState.REVIEW
                self._current_pending.set(None, t_mono_ns=time.monotonic_ns())
                if self._pending:
                    self._pending.finalize()
                    self._pending.discard()
                    self._pending = None
                self.session.state = SessionState.READY

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """IDLE -> READY. Connect adapters, spawn all tasks."""
        if self.session.state != SessionState.IDLE:
            raise InvalidTransitionError(
                f"start requires IDLE, got {self.session.state}"
            )

        precheck_start(StartSessionRequestDomain(robot=self._robot, mode=self.session.mode))

        await self._robot.connect()
        if self._teleop:
            await self._teleop.connect()
        await self._cameras.start()

        # Set current_pending to None initially
        self._current_pending.set(None, t_mono_ns=0)

        # Spawn readers
        self._robot_reader_task = asyncio.create_task(self._run_robot_reader())
        if self._teleop:
            self._teleop_reader_task = asyncio.create_task(self._run_teleop_reader())

        # Camera slots
        camera_slots = {name: self._cameras.latest(name) for name in self._cameras._cameras}

        # Spawn control loop
        if self.session.mode == SessionMode.TELEOP:
            self._control_loop_task = asyncio.create_task(run_teleop_control_loop(
                session=self.session, fps=self._fps,
                robot_state_slot=self._robot_state_slot,
                teleop_slot=self._teleop_slot,
                camera_slots=camera_slots,
                command_goal_slot=self._command_goal_slot,
                mapper=self._mapper,
                enqueue=self._recorder_queue.put_nowait,
                clock=RealClock(), metrics=self._metrics,
            ))
        else:
            self._control_loop_task = asyncio.create_task(run_handteach_control_loop(
                session=self.session, fps=self._fps,
                robot_adapter=self._robot,
                robot_state_slot=self._robot_state_slot,
                camera_slots=camera_slots,
                enqueue=self._recorder_queue.put_nowait,
                clock=RealClock(), metrics=self._metrics,
            ))

        # Spawn dispatcher
        self._dispatcher_task = asyncio.create_task(run_command_dispatcher(
            self._robot, self._command_goal_slot, self._error_bus, self.session.stopped,
        ))

        # Spawn writer
        self._writer_task = asyncio.create_task(run_writer(
            current_pending=self._current_pending,
            queue=self._recorder_queue,
            metrics=self._metrics,
            stopped=self.session.stopped,
            fk=self._fk,
        ))

        # Error handler
        self._error_handler_task = asyncio.create_task(self._handle_errors())

        self.session.state = SessionState.READY

    async def episode_start(self) -> None:
        """READY -> RECORDING. Create PendingEpisode, open video writers."""
        assert_can_start_episode(self.session)
        self._pending = PendingEpisode.open(self._dataset_root, self._episode_index)
        # Open video writers for cameras that have produced a frame
        cam_sizes: dict[str, tuple[int, int]] = {}
        for name in self._cameras._cameras:
            s = self._cameras.latest(name).peek()
            if s is not None:
                h, w = s.value.image.shape[:2]
                cam_sizes[name] = (w, h)
        if cam_sizes:
            self._pending.open_video_writers(fps=self._fps, cameras=cam_sizes)
        self._current_pending.set(self._pending, t_mono_ns=time.monotonic_ns())
        self._episode_start_t_mono_ns = time.monotonic_ns()
        self.session.state = SessionState.RECORDING

    async def episode_stop(self) -> None:
        """RECORDING -> REVIEW. Clear pending slot, drain queue, finalize."""
        if self.session.state != SessionState.RECORDING:
            raise InvalidTransitionError(
                f"episode_stop requires RECORDING, got {self.session.state}"
            )
        self.session.state = SessionState.REVIEW
        self._current_pending.set(None, t_mono_ns=time.monotonic_ns())
        # Give writer time to drain
        for _ in range(100):
            if self._recorder_queue.empty():
                break
            await asyncio.sleep(0.01)
        if self._pending:
            self._pending.finalize()

    async def episode_save(self, success: bool | None = None, comment: str | None = None) -> None:
        """REVIEW -> READY. Save pending episode with metadata."""
        if self.session.state != SessionState.REVIEW:
            raise InvalidTransitionError(
                f"episode_save requires REVIEW, got {self.session.state}"
            )
        if self._pending:
            now_mono = time.monotonic_ns()
            # Make sure tasks.parquet has an entry for this task name so the
            # task -> task_index mapping is consistent across episodes.
            from mimicrec.recording.metadata import upsert_task
            upsert_task(
                self._dataset_root / "meta",
                self._task,
                self._instruction,
            )
            self._pending.save(metadata_extra={
                "episode_index": self._episode_index,
                "task": self._task,
                "instruction": self._instruction,
                "robot": self._robot.name,
                "teleop": self._teleop.name if self._teleop else None,
                "mapper": "identity",
                "cameras": list(self._cameras._cameras.keys()),
                "mode": self.session.mode.value,
                "fps": self._fps,
                "success": success,
                "comment": comment,
                "start_t_mono_ns": self._episode_start_t_mono_ns or 0,
                "end_t_mono_ns": now_mono,
                "duration_sec": (now_mono - (self._episode_start_t_mono_ns or now_mono)) / 1e9,
                "num_frames": self._metrics.get("writer_rows_written"),
                "session_boot_t_unix": 0,
                "session_boot_t_mono_ns": 0,
                "resolved_config": self._resolved_config,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            })
            self._pending = None
            self._episode_index += 1
        self.session.state = SessionState.READY

    async def episode_discard(self) -> None:
        """REVIEW -> READY. Discard pending episode."""
        if self.session.state != SessionState.REVIEW:
            raise InvalidTransitionError(
                f"episode_discard requires REVIEW, got {self.session.state}"
            )
        if self._pending:
            self._pending.discard()
            self._pending = None
        self.session.state = SessionState.READY

    async def replay_start(self, trajectory) -> None:
        """READY (not replay_active) -> spawn replay task."""
        from mimicrec.session.replay import run_replay
        if self.session.state != SessionState.READY:
            raise InvalidTransitionError(
                f"replay_start requires READY, got {self.session.state}"
            )
        if self.session.replay_active:
            raise InvalidTransitionError("another replay is already active")
        self._replay_task = asyncio.create_task(run_replay(
            session=self.session,
            trajectory=trajectory,
            fps=self._fps,
            command_goal_slot=self._command_goal_slot,
            clock=RealClock(),
            measured_state_slot=self._robot_state_slot,
            safety=self._replay_safety,
            error_bus=self._error_bus,
        ))

    async def replay_stop(self) -> None:
        """Clear replay_active, await replay task."""
        self.session.replay_active = False
        if self._replay_task and not self._replay_task.done():
            self._replay_task.cancel()
            try:
                await self._replay_task
            except (asyncio.CancelledError, Exception):
                pass
        self._replay_task = None

    async def end(self) -> None:
        """Any -> IDLE. Shut down everything in order."""
        self.session.stopped.set()
        # Cancel replay if active
        if self._replay_task and not self._replay_task.done():
            self.session.replay_active = False
            self._replay_task.cancel()
            try:
                await self._replay_task
            except (asyncio.CancelledError, Exception):
                pass

        # Discard any pending episode
        if self._pending:
            self._current_pending.set(None, t_mono_ns=0)
            self._pending.discard()
            self._pending = None

        # Await tasks in order
        for task in [
            self._teleop_reader_task, self._robot_reader_task,
            self._control_loop_task, self._writer_task,
            self._dispatcher_task, self._error_handler_task,
        ]:
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    pass

        await self._cameras.stop()
        await self._robot.disconnect()
        if self._teleop:
            await self._teleop.disconnect()

        self.session.state = SessionState.IDLE
