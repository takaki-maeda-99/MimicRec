from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from mimicrec.adapters.robot import RobotAdapter, RobotMode
from mimicrec.cameras.manager import CameraManager
from mimicrec.errors import (
    FatalHardwareError,
    HandTeachNotSupportedError,
    HardwareError,
    InvalidTransitionError,
)
from mimicrec.recording.pending import PendingEpisode
from mimicrec.session.control_loop import run_handteach_control_loop, run_teleop_control_loop
from mimicrec.session.dispatcher import run_command_dispatcher
from mimicrec.session.replay_safety import ReplaySafetyConfig
from mimicrec.session.state import Session
from mimicrec.recording.writer import run_writer
from mimicrec.inference.chunk_buffer import ChunkBuffer
from mimicrec.inference.safety import InferenceSafety
from mimicrec.inference.producer import run_inference_producer
from mimicrec.inference.control_loop import run_inference_control_loop
from mimicrec.inference.action_decoder import ActionDecoder
from mimicrec.inference.client import InferenceClient
from mimicrec.inference.contract import ContractSpec
from mimicrec.kinematics.ik import IKService
import numpy as np

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
        # ``_episode_start_t_mono_ns`` is set when state→RECORDING.
        # ``_episode_stop_t_mono_ns`` is set when state→REVIEW (i.e. the
        # operator pressed Stop). The metadata's ``duration_sec`` uses the
        # gap between these, NOT the gap to ``episode_save`` time — that
        # would include the REVIEW window where the user decides to save
        # or discard, and inflate every duration by several seconds.
        self._episode_start_t_mono_ns: int | None = None
        self._episode_stop_t_mono_ns: int | None = None

        # Replay needs the daemon in POSITION mode; remember what mode the
        # session was running in so replay_stop can restore it. None = no
        # mode switch was performed (e.g. adapter doesn't support modes /
        # set_mode failed soft).
        self._mode_before_replay: RobotMode | None = None

        # Inference subsystem (populated by start_inference_session)
        self._robot_config_dict: dict = self._resolved_config.get("robot", {})
        self._instruction_slot: LatestValue[str] = LatestValue()
        self._chunk_buffer: ChunkBuffer | None = None
        self._inference_safety: InferenceSafety | None = None
        self._producer_task: asyncio.Task | None = None
        self._inference_watchdog_task: asyncio.Task | None = None
        self._inference_client: InferenceClient | None = None
        self._inference_config_name: str | None = None
        self._last_stop_reason: str | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> SessionState:
        return self.session.state

    # ------------------------------------------------------------------
    # Reader tasks
    # ------------------------------------------------------------------

    # Number of consecutive reader failures before declaring the bus dead and
    # ending the session. At ~100 Hz read attempts this is ~1 second of pure
    # failure — fine to forgive momentary blips, but signals "the motors are
    # not coming back" (e.g. Feetech overload alarm latched).
    _MAX_CONSECUTIVE_READER_ERRORS = 100

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
                if consecutive_errors == 1 or consecutive_errors % 100 == 0:
                    logger.warning(
                        "robot reader error (#%d): %s: %s",
                        consecutive_errors, type(e).__name__, e,
                    )
                if consecutive_errors >= self._MAX_CONSECUTIVE_READER_ERRORS:
                    logger.error(
                        "robot reader: %d consecutive failures, declaring "
                        "the bus dead and ending the session",
                        consecutive_errors,
                    )
                    await self._error_bus.publish(FatalHardwareError(
                        f"robot bus unresponsive after {consecutive_errors} "
                        f"reads (last error: {type(e).__name__}: {e}). "
                        f"Power-cycle the arm and start a new session."
                    ))
                    return
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
                if consecutive_errors >= self._MAX_CONSECUTIVE_READER_ERRORS:
                    logger.error(
                        "teleop reader: %d consecutive failures, declaring "
                        "the leader bus dead and ending the session",
                        consecutive_errors,
                    )
                    await self._error_bus.publish(FatalHardwareError(
                        f"teleop bus unresponsive after {consecutive_errors} "
                        f"reads (last error: {type(e).__name__}: {e}). "
                        f"Power-cycle the leader arm and start a new session."
                    ))
                    return
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
            # Only escalate to a full session end on FATAL hardware errors
            # (e.g. persistent reader failure declared by the robot reader
            # after MAX_CONSECUTIVE_READER_ERRORS, or an explicit operator
            # E-stop). Plain HardwareErrors are transient by definition —
            # the camera manager publishes one whenever a single V4L2 read
            # times out, and the camera task immediately continues. The
            # parquet writer skips that tick's video frame and moves on,
            # so the episode stays well-formed even with a few drops.
            # Auto-discarding the in-flight episode on every transient
            # error meant 30 seconds of hand-teach got thrown away because
            # of one missed USB frame; we now log and let the user decide.
            if isinstance(evt, FatalHardwareError):
                logger.error("FatalHardwareError received — ending session: %s", evt)
                asyncio.create_task(self.end())
                return
            if isinstance(evt, HardwareError):
                logger.warning("transient HardwareError (recording continues): %s", evt)

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

        # Resume episode_index numbering from where the dataset left off.
        # SessionManager is reconstructed per session, so without this every
        # new session starts at 0 and overwrites episode_000000.parquet.
        from mimicrec.recording.metadata import read_episodes
        try:
            existing = list(read_episodes(self._dataset_root / "meta", include_deleted=True))
            if existing:
                self._episode_index = max(int(e["episode_index"]) for e in existing) + 1
        except FileNotFoundError:
            pass

        await self._robot.connect()
        if self._teleop:
            await self._teleop.connect()
        await self._cameras.start()

        # Align the robot mode with the session's intent. Adapters that
        # gate send_joint_command on mode (notably the reBotArm daemon)
        # will silently or noisily refuse otherwise. Hand-teach is the only
        # mode that wants the controller to leave the arm compliant; all
        # other session modes need POSITION so the dispatcher can issue
        # joint commands.
        target_mode = (
            RobotMode.GRAVITY_COMP
            if self.session.mode == SessionMode.HAND_TEACH
            else RobotMode.POSITION
        )
        try:
            await self._robot.set_mode(target_mode)
        except (HardwareError, NotImplementedError):
            # Adapters that don't support set_mode (or fail soft) will
            # surface mode mismatches via downstream dispatch errors.
            logger.warning(
                "robot adapter %r refused set_mode(%s); proceeding",
                self._robot.name, target_mode,
            )

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
        self._episode_stop_t_mono_ns = None
        self.session.state = SessionState.RECORDING

    async def episode_stop(self) -> None:
        """RECORDING -> REVIEW. Drain writer, clear pending slot, finalize."""
        if self.session.state != SessionState.RECORDING:
            raise InvalidTransitionError(
                f"episode_stop requires RECORDING, got {self.session.state}"
            )
        # Move out of RECORDING so the control loop stops enqueuing new
        # bundles. The pending slot stays non-None until drain finishes —
        # flipping it earlier caused the writer to drop every queued
        # bundle on its next iteration, which truncated long recordings
        # to whatever the writer happened to have caught up to (e.g. 3 s
        # saved out of 10 s recorded).
        self._episode_stop_t_mono_ns = time.monotonic_ns()
        self.session.state = SessionState.REVIEW
        # Wait for the writer to fully process every queued bundle —
        # both the get() and the executor-side append_row must complete
        # before we touch the pending episode. ``queue.join()`` is the
        # canonical way to express that: it returns once every put has
        # been balanced by a task_done. ``queue.empty()`` would lie
        # while the writer is mid-encode in the executor thread.
        try:
            await asyncio.wait_for(self._recorder_queue.join(), timeout=60.0)
        except asyncio.TimeoutError:
            logger.warning(
                "episode_stop: writer drain timed out after 60 s; pending "
                "episode is missing trailing frames. Encoder is likely "
                "falling behind realtime — check Mp4EpisodeWriter preset."
            )
        # Drained — safe to clear the pending slot and finalize.
        self._current_pending.set(None, t_mono_ns=time.monotonic_ns())
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
            # Use the stop timestamp (set when state→REVIEW), not now_mono,
            # so duration reflects only the RECORDING window. Reviewing for
            # 3 s before saving used to add 3 s to every duration_sec.
            stop_t = self._episode_stop_t_mono_ns or now_mono
            start_t = self._episode_start_t_mono_ns or stop_t
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
                "start_t_mono_ns": start_t,
                "end_t_mono_ns": stop_t,
                "duration_sec": (stop_t - start_t) / 1e9,
                # Per-episode count (writer_rows_written is session-cumulative).
                "num_frames": self._pending.num_frames,
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

        # Validate trajectory shape BEFORE flipping the daemon into POSITION:
        # mode transitions briefly drop motor torque (~200 ms stabilize per
        # motor), so a validation failure after set_mode would leave the arm
        # falling under gravity for the round-trip. Trajectories with extra
        # columns (e.g. gripper appended by hand-teach recording) are tolerated
        # — run_replay slices to arm dof. Trajectories with fewer columns than
        # arm dof can't be played and we abort here.
        if (
            trajectory.joint_targets.ndim != 2
            or trajectory.joint_targets.shape[1] < self._robot.dof
        ):
            from mimicrec.errors import ReplaySafetyError
            raise ReplaySafetyError(
                f"replay trajectory has {trajectory.joint_targets.shape} cols; "
                f"need at least {self._robot.dof} for arm dof"
            )

        # Flip the adapter into POSITION mode BEFORE spawning the replay
        # task, otherwise the daemon's control loop ignores the position
        # targets we feed via command_goal_slot. Hand-teach sessions sit in
        # GRAVITY_COMP, so without this the replay path silently no-ops.
        # We remember the prior mode and restore it in replay_stop.
        await self._robot.set_mode(RobotMode.POSITION)
        # Track what we need to restore. Hand-teach sessions came from
        # GRAVITY_COMP; teleop already runs in POSITION.
        self._mode_before_replay = (
            RobotMode.GRAVITY_COMP
            if self.session.mode == SessionMode.HAND_TEACH
            else RobotMode.POSITION
        )

        async def _run_with_restore() -> None:
            # Wrap run_replay so the prior mode is restored on ANY exit —
            # normal completion, ReplaySafetyError, cancellation. Without
            # this, a safety trip leaves the daemon in POSITION holding
            # pose, which the operator perceives as the arm "stiffening".
            try:
                await run_replay(
                    session=self.session,
                    trajectory=trajectory,
                    fps=self._fps,
                    command_goal_slot=self._command_goal_slot,
                    clock=RealClock(),
                    measured_state_slot=self._robot_state_slot,
                    safety=self._replay_safety,
                    error_bus=self._error_bus,
                )
            finally:
                await self._restore_mode_after_replay()

        self._replay_task = asyncio.create_task(_run_with_restore())

    async def _restore_mode_after_replay(self) -> None:
        """Restore the robot mode captured in replay_start.

        Called from both the replay task's ``finally`` (so safety trips
        auto-recover) and from ``replay_stop`` (user-initiated stop).
        Idempotent: clears ``_mode_before_replay`` on first call.
        """
        if self._mode_before_replay is None:
            return
        prev = self._mode_before_replay
        self._mode_before_replay = None
        try:
            await self._robot.set_mode(prev)
        except (HardwareError, Exception) as e:
            logger.warning(
                "replay restore: failed to set robot mode %s: %s", prev, e,
            )

    async def replay_stop(self) -> None:
        """Clear replay_active, await replay task, restore prior robot mode."""
        self.session.replay_active = False
        if self._replay_task and not self._replay_task.done():
            self._replay_task.cancel()
            try:
                await self._replay_task
            except (asyncio.CancelledError, Exception):
                pass
        self._replay_task = None
        # Idempotent: the replay task's finally already calls this on its
        # way out, but in race cases (cancel before the finally fires) we
        # call it again here to make sure mode is restored.
        await self._restore_mode_after_replay()

    # ------------------------------------------------------------------
    # Inference safety config helper
    # ------------------------------------------------------------------

    def _robot_safety_config(self) -> dict | None:
        """Read inference_safety: from the active robot's YAML config."""
        cfg = (self._robot_config_dict or {}).get("inference_safety")
        if cfg is None:
            return None
        joint_names = self._robot.joint_names
        limits = cfg["joint_limits_deg"]
        joint_min = np.array([limits[n][0] for n in joint_names])
        joint_max = np.array([limits[n][1] for n in joint_names])
        return {
            "max_joint_delta_per_step_deg": cfg["max_joint_delta_per_step_deg"],
            "slow_stop_ticks": cfg.get("slow_stop_ticks", 5),
            "joint_min": joint_min,
            "joint_max": joint_max,
        }

    # ------------------------------------------------------------------
    # Inference session lifecycle
    # ------------------------------------------------------------------

    async def start_inference_session(
        self,
        contract: ContractSpec,
        instruction: str,
        inference_config_name: str,
    ) -> None:
        """Replaces start_recording_session for INFERENCE mode."""
        if self.session.state != SessionState.READY:
            raise InvalidTransitionError(
                f"start_inference_session requires READY, got {self.session.state}"
            )

        self.session.mode = SessionMode.INFERENCE
        self._inference_config_name = inference_config_name
        self._instruction_slot.set(instruction, t_mono_ns=0)
        self.session.locked_instruction = None
        self.session.producer_paused = False
        self._last_stop_reason = None

        # Build inference subsystem.
        # `resolve_action_stats()` returns None when normalization.method == "none",
        # so we can call it unconditionally and pass the result straight through.
        action_stats = contract.resolve_action_stats()
        self._chunk_buffer = ChunkBuffer.create(
            prefetch_threshold=contract.loop.prefetch_threshold,
        )
        safety_cfg = self._robot_safety_config()
        if safety_cfg is None:
            raise InvalidTransitionError("inference_safety block is required in robot config")
        self._inference_safety = InferenceSafety(
            max_delta=safety_cfg["max_joint_delta_per_step_deg"],
            joint_min=safety_cfg["joint_min"],
            joint_max=safety_cfg["joint_max"],
            slow_stop_ticks=safety_cfg["slow_stop_ticks"],
        )

        # Spawn readers same as TELEOP, except teleop reader is NOT spawned
        self._robot_reader_task = asyncio.create_task(self._run_robot_reader())
        camera_slots = {name: self._cameras.latest(name) for name in self._cameras._cameras}

        fk = self._fk
        ik = IKService(fk.cfg)  # FKService.cfg is public (see Task 5b)
        decoder = ActionDecoder(
            spec=contract, fk=fk, ik=ik,
            narm=self._robot.dof,
            action_stats=action_stats,
        )
        client = InferenceClient(spec=contract)
        self._inference_client = client

        self._producer_task = asyncio.create_task(run_inference_producer(
            client=client, decoder=decoder, buffer=self._chunk_buffer,
            camera_slots=camera_slots, robot_state_slot=self._robot_state_slot,
            instruction_slot=self._instruction_slot, safety=self._inference_safety,
            session=self.session, metrics=self._metrics, error_bus=self._error_bus,
        ))
        self._control_loop_task = asyncio.create_task(run_inference_control_loop(
            session=self.session, fps=self._fps,
            robot_state_slot=self._robot_state_slot, camera_slots=camera_slots,
            chunk_buffer=self._chunk_buffer, safety=self._inference_safety,
            command_goal_slot=self._command_goal_slot,
            enqueue=self._recorder_queue.put_nowait,
            clock=RealClock(), metrics=self._metrics,
        ))
        self._dispatcher_task = asyncio.create_task(run_command_dispatcher(
            self._robot, self._command_goal_slot, self._error_bus, self.session.stopped,
        ))
        self._writer_task = asyncio.create_task(run_writer(
            current_pending=self._current_pending,
            queue=self._recorder_queue, metrics=self._metrics,
            stopped=self.session.stopped, fk=self._fk,
        ))

    async def stop_inference_session(self) -> None:
        self.session.stopped.set()
        for t in (
            self._producer_task, self._control_loop_task,
            self._dispatcher_task, self._writer_task, self._robot_reader_task,
        ):
            if t is not None:
                t.cancel()
        if self._inference_client is not None:
            await self._inference_client.aclose()

    def pause_producer_and_flush(self) -> int:
        """Order-locked: producer_paused FIRST, then flush.
        Returns the flushed step count for telemetry."""
        self.session.producer_paused = True
        return self._chunk_buffer.flush() if self._chunk_buffer else 0

    def resume_producer(self) -> None:
        self.session.producer_paused = False
        if self._chunk_buffer is not None:
            self._chunk_buffer.request_refill_now()

    def inference_state_snapshot(self) -> dict:
        """Return the current INFERENCE-mode session state for polling clients.
        Reads in-memory state only (no I/O). Returns {phase: pre_start} when not
        currently in INFERENCE mode."""
        if self.session.mode != SessionMode.INFERENCE:
            return {"phase": "pre_start"}
        instr = self._instruction_slot.peek()
        return {
            "phase": self.session.state.value,
            "instruction": instr.value if instr is not None else None,
            "locked_instruction": self.session.locked_instruction,
            "buffer_depth": self._chunk_buffer.depth() if self._chunk_buffer else 0,
            "buffer_origin": self._chunk_buffer.origin_size() if self._chunk_buffer else 0,
            "chunks_consumed": self._metrics.get("chunks_consumed"),
            "last_inference_latency_ms": self._metrics.get_last("inference_latency_ms"),
            "inference_errors": self._metrics.get("inference_error_count"),
            "last_safety_event": self._inference_safety.last_event() if self._inference_safety else None,
        }

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
