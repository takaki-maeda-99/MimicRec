"""Motion sources and bridges from the legacy teleoperator contract."""
from __future__ import annotations

import time
from typing import Protocol
import asyncio

import numpy as np
from scipy.spatial.transform import Rotation

from mimicrec.motion.se3 import SE3Delta, SE3Frame
from mimicrec.motion.types import MotionStep
from mimicrec.types import TeleopAction


class MotionSource(Protocol):
    name: str
    control_rate_hz: float

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def read_step(self) -> MotionStep: ...


class TeleopActionConverter:
    """Convert legacy deltas or clutch-relative poses into per-step SE(3)."""

    def __init__(
        self,
        *,
        frame: SE3Frame | str = SE3Frame.EE_LOCAL,
        default_rate_hz: float = 60.0,
    ) -> None:
        if default_rate_hz <= 0.0:
            raise ValueError("default_rate_hz must be > 0")
        self.frame = SE3Frame(frame)
        self.default_duration_sec = 1.0 / float(default_rate_hz)
        self._last_pose_transform: np.ndarray | None = None
        self._last_t_mono_ns: int | None = None

    def reset(self) -> None:
        self._last_pose_transform = None
        self._last_t_mono_ns = None

    def convert(self, action: TeleopAction) -> MotionStep | None:
        if action.ee_pose_active is False:
            self.reset()
            return None

        stamp = int(action.t_mono_ns or time.monotonic_ns())
        duration = self.default_duration_sec
        if self._last_t_mono_ns is not None and stamp > self._last_t_mono_ns:
            # Bound transport stalls: one delayed packet must not encode a huge
            # duration that later turns into an artificially tiny velocity.
            duration = min(max((stamp - self._last_t_mono_ns) / 1e9, 1e-4), 0.1)
        self._last_t_mono_ns = stamp

        tangent: np.ndarray
        if action.ee_world_pose_offset is not None:
            if self.frame != SE3Frame.WORLD:
                raise ValueError("ee_world_pose_offset requires frame='world'")
            offset = np.asarray(action.ee_world_pose_offset, dtype=np.float64)
            if offset.shape != (6,) or not np.isfinite(offset).all():
                raise ValueError(
                    "ee_world_pose_offset must be a finite length-6 vector"
                )
            pose = np.eye(4, dtype=np.float64)
            pose[:3, :3] = Rotation.from_rotvec(offset[3:].copy()).as_matrix()
            pose[:3, 3] = offset[:3]
            control_rotation = None
            if action.ee_control_rotation_offset is not None:
                control_rotvec = np.asarray(
                    action.ee_control_rotation_offset, dtype=np.float64
                )
                if (
                    control_rotvec.shape != (3,)
                    or not np.isfinite(control_rotvec).all()
                ):
                    raise ValueError(
                        "ee_control_rotation_offset must be a finite length-3 vector"
                    )
                control_rotation = Rotation.from_rotvec(
                    control_rotvec.copy()
                ).as_matrix()
            reset_reference = self._last_pose_transform is None
            if reset_reference:
                step_transform = np.eye(4, dtype=np.float64)
            else:
                step_transform = np.eye(4, dtype=np.float64)
                step_transform[:3, 3] = (
                    pose[:3, 3] - self._last_pose_transform[:3, 3]
                )
                # Spatial/WORLD rotation increment. Translation is the
                # displacement of the tracked point, never an origin orbit.
                step_transform[:3, :3] = (
                    pose[:3, :3] @ self._last_pose_transform[:3, :3].T
                )
            self._last_pose_transform = pose
            return MotionStep(
                delta=SE3Delta.from_transform(
                    step_transform,
                    frame=self.frame,
                    duration_sec=duration,
                ),
                auxiliary={
                    "gripper": float(action.gripper_fraction)
                } if action.gripper_fraction is not None else {},
                t_mono_ns=stamp,
                absolute_offset=pose,
                control_rotation_offset=control_rotation,
                reset_reference=reset_reference,
            )
        if action.ee_pose_offset is not None:
            offset = np.asarray(action.ee_pose_offset, dtype=np.float64)
            if offset.shape != (6,) or not np.isfinite(offset).all():
                raise ValueError("ee_pose_offset must be a finite length-6 vector")
            # Legacy pose offsets store the transform's literal translation
            # column plus a rotation vector, not an se(3) logarithm. Build ΔT
            # explicitly before taking the relative Log between samples.
            pose = np.eye(4, dtype=np.float64)
            pose[:3, :3] = Rotation.from_rotvec(offset[3:].copy()).as_matrix()
            pose[:3, 3] = offset[:3]
            if self._last_pose_transform is None:
                tangent = np.zeros(6, dtype=np.float64)
            else:
                # Body/local increment: previous controller-relative pose to
                # current controller-relative pose.
                relative = np.linalg.inv(self._last_pose_transform) @ pose
                tangent = SE3Delta.from_transform(
                    relative, frame=self.frame, duration_sec=duration
                ).tangent.copy()
            self._last_pose_transform = pose
        elif action.ee_cartesian_delta is not None:
            components = np.asarray(
                action.ee_cartesian_delta, dtype=np.float64
            )
            if components.shape != (6,) or not np.isfinite(components).all():
                raise ValueError(
                    "ee_cartesian_delta must be a finite length-6 vector"
                )
            transform = np.eye(4, dtype=np.float64)
            transform[:3, :3] = Rotation.from_rotvec(
                components[3:].copy()
            ).as_matrix()
            transform[:3, 3] = components[:3]
            return MotionStep(
                delta=SE3Delta.from_transform(
                    transform,
                    frame=self.frame,
                    duration_sec=duration,
                ),
                auxiliary={
                    "gripper": float(action.gripper_fraction)
                } if action.gripper_fraction is not None else {},
                t_mono_ns=stamp,
            )
        elif action.ee_delta is not None:
            tangent = np.asarray(action.ee_delta, dtype=np.float64)
        else:
            return None

        auxiliary: dict[str, float] = {}
        if action.gripper_fraction is not None:
            auxiliary["gripper"] = float(action.gripper_fraction)
        if action.gripper_delta is not None:
            auxiliary["gripper_delta"] = float(action.gripper_delta)
        return MotionStep(
            delta=SE3Delta(tangent, frame=self.frame, duration_sec=duration),
            auxiliary=auxiliary,
            t_mono_ns=stamp,
        )


class LegacyTeleopMotionSource:
    """Adapt an existing Teleoperator into a MotionSource."""

    def __init__(
        self,
        teleop,
        *,
        frame: SE3Frame | str = SE3Frame.EE_LOCAL,
        default_rate_hz: float | None = None,
    ) -> None:
        self.teleop = teleop
        self.name = str(teleop.name)
        self.control_rate_hz = float(
            default_rate_hz
            or getattr(teleop, "control_rate_hz", 60.0)
        )
        self.converter = TeleopActionConverter(
            frame=frame, default_rate_hz=self.control_rate_hz
        )
        self._last_pose_sequence = -1

    async def connect(self) -> None:
        self.converter.reset()
        self._last_pose_sequence = -1
        await self.teleop.connect()

    async def disconnect(self) -> None:
        await self.teleop.disconnect()

    async def read_step(self) -> MotionStep:
        while True:
            action = await self.teleop.read_action()
            if (
                action.ee_pose_offset is not None
                or action.ee_cartesian_delta is not None
                or action.ee_world_pose_offset is not None
            ):
                sequence = int(getattr(self.teleop, "pose_message_sequence", 0))
                if sequence == self._last_pose_sequence:
                    # WebTeleoperator exposes the latest absolute offset on
                    # every poll. Re-tokenizing the same sample would produce
                    # zero increments that can overwrite the one real update
                    # before a 60 Hz Motion Group consumes it.
                    continue
                self._last_pose_sequence = sequence
            step = self.converter.convert(action)
            if step is not None:
                return step


class MotionTeleopRouter:
    """Route one WebSocket endpoint into independently named teleoperators."""

    name = "motion_router"
    control_mode = "ee_delta"

    def __init__(self, channels: dict[str, object], *, default_channel: str):
        if not channels or default_channel not in channels:
            raise ValueError("MotionTeleopRouter requires a valid default channel")
        self.channels = dict(channels)
        self.default_channel = default_channel
        self.input_queue: asyncio.Queue = asyncio.Queue()
        self.home_requests: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def connect(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(
                self._run(), name="motion-teleop-router"
            )

    async def disconnect(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        self.stop_motion()

    async def _run(self) -> None:
        while True:
            message = await self.input_queue.get()
            try:
                channel = str(message.get("channel", self.default_channel))
                target = self.channels.get(channel)
                if target is not None:
                    if message.get("cmd") == "home":
                        self.home_requests.put_nowait(channel)
                    await target.input_queue.put(message)
            finally:
                self.input_queue.task_done()

    def stop_motion(self, channel: str | None = None) -> None:
        targets = (
            [self.channels[channel]]
            if channel is not None and channel in self.channels
            else self.channels.values()
        )
        for target in targets:
            stop = getattr(target, "stop_motion", None)
            if stop is not None:
                stop()
