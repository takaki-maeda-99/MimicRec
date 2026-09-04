"""Web-based keyboard teleoperator.

Receives joint deltas from a browser WebSocket via an asyncio.Queue.
The frontend captures keyboard events and sends them as JSON:
    {"joint": 0, "delta": 0.05}  — increment joint 0 by 0.05 rad
    {"joint": 0, "delta": -0.05} — decrement

For Cartesian control, browser axes are persistent while held. External
bridges can instead send SI velocities, or an absolute Cartesian offset from a
clutch reference pose. Inputs automatically expire when they become stale.

The adapter maintains a running target position and returns it on read_action().
"""

from __future__ import annotations

import asyncio
import time

import numpy as np

from mimicrec.adapters.teleop import TeleopType
from mimicrec.types import TeleopAction


class WebTeleoperator:
    name = "web_keyboard"
    type = TeleopType.KEYBOARD

    def __init__(
        self,
        dof: int = 9,
        control_mode: str = "joint",
        linear_step_m: float = 0.001,
        angular_step_rad: float = 0.01,
        gripper_step_rad: float = 0.02,
        control_rate_hz: int | None = None,
        input_timeout_sec: float = 0.3,
    ):
        if control_mode not in {"joint", "ee_delta"}:
            raise ValueError("control_mode must be 'joint' or 'ee_delta'")
        self._dof = dof
        self.control_mode = control_mode
        self._target = np.zeros(dof, dtype=np.float32)
        self._ee_axes = np.zeros(6, dtype=np.float32)
        self._gripper_axis = 0.0
        self._linear_step_m = float(linear_step_m)
        self._angular_step_rad = float(angular_step_rad)
        self._gripper_step_rad = float(gripper_step_rad)
        self.control_rate_hz = control_rate_hz
        self._input_timeout_sec = float(input_timeout_sec)
        self._monotonic = time.monotonic
        self._ee_velocity = np.zeros(6, dtype=np.float32)
        self._ee_cartesian_delta: np.ndarray | None = None
        self._ee_world_pose_offset: np.ndarray | None = None
        self._ee_control_rotation_offset: np.ndarray | None = None
        self._ee_pose_offset: np.ndarray | None = None
        self._ee_pose_active = False
        self._gripper_velocity = 0.0
        self._gripper_fraction: float | None = None
        self._pose_message_sequence = 0
        self._pose_release_required = False
        self._last_velocity_input_at: float | None = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._initialized = control_mode == "ee_delta"

    @property
    def input_queue(self) -> asyncio.Queue:
        """Queue for receiving teleop commands from WebSocket hub."""
        return self._queue

    @property
    def pose_message_sequence(self) -> int:
        return self._pose_message_sequence

    def require_pose_release(self) -> None:
        """Ignore pose input until a subsequent physical release/stop."""
        self.stop_motion()
        self._pose_release_required = True

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def read_action(self) -> TeleopAction:
        home_requested = False
        # Drain all pending deltas (non-blocking)
        while not self._queue.empty():
            try:
                msg = self._queue.get_nowait()
                joint = msg.get("joint", 0)
                delta = msg.get("delta", 0.0)
                # "reset" command: set target to current robot state
                if msg.get("cmd") == "reset" and "pos" in msg:
                    self._target = np.array(msg["pos"], dtype=np.float32)
                    self._initialized = True
                elif msg.get("cmd") == "ee_axes" and self.control_mode == "ee_delta":
                    axes = np.asarray(msg.get("axes", []), dtype=np.float32)
                    if axes.shape == (6,) and np.isfinite(axes).all():
                        self._ee_axes = np.clip(axes, -1.0, 1.0)
                        grip = float(msg.get("gripper", 0.0))
                        self._gripper_axis = float(np.clip(grip, -1.0, 1.0))
                        self._ee_velocity.fill(0.0)
                        self._ee_pose_offset = None
                        self._ee_cartesian_delta = None
                        self._ee_world_pose_offset = None
                        self._ee_control_rotation_offset = None
                        self._ee_pose_active = False
                        self._gripper_velocity = 0.0
                        self._last_velocity_input_at = None
                elif msg.get("cmd") == "ee_velocity" and self.control_mode == "ee_delta":
                    velocity = np.asarray(msg.get("velocity", []), dtype=np.float32)
                    try:
                        gripper_velocity = float(msg.get("gripper_velocity", 0.0))
                    except (TypeError, ValueError):
                        continue
                    if (
                        velocity.shape == (6,)
                        and np.isfinite(velocity).all()
                        and np.isfinite(gripper_velocity)
                    ):
                        self._ee_velocity = velocity
                        self._gripper_velocity = gripper_velocity
                        self._ee_axes.fill(0.0)
                        self._gripper_axis = 0.0
                        self._ee_pose_offset = None
                        self._ee_cartesian_delta = None
                        self._ee_world_pose_offset = None
                        self._ee_control_rotation_offset = None
                        self._ee_pose_active = False
                        self._last_velocity_input_at = self._monotonic()
                elif msg.get("cmd") == "ee_world_delta" and self.control_mode == "ee_delta":
                    delta = np.asarray(msg.get("delta", []), dtype=np.float32)
                    try:
                        fraction_raw = msg.get("gripper_fraction")
                        fraction = (
                            None if fraction_raw is None else float(fraction_raw)
                        )
                    except (TypeError, ValueError):
                        continue
                    if (
                        delta.shape == (6,)
                        and np.isfinite(delta).all()
                        and (fraction is None or np.isfinite(fraction))
                    ):
                        self._pose_message_sequence += 1
                        if self._pose_release_required:
                            continue
                        self._ee_cartesian_delta = delta
                        self._ee_world_pose_offset = None
                        self._ee_control_rotation_offset = None
                        self._gripper_fraction = (
                            None if fraction is None
                            else float(np.clip(fraction, 0.0, 1.0))
                        )
                        self._ee_pose_offset = None
                        self._ee_pose_active = True
                        self._ee_axes.fill(0.0)
                        self._gripper_axis = 0.0
                        self._ee_velocity.fill(0.0)
                        self._gripper_velocity = 0.0
                        self._last_velocity_input_at = self._monotonic()
                elif msg.get("cmd") == "ee_world_pose_offset" and self.control_mode == "ee_delta":
                    offset = np.asarray(msg.get("offset", []), dtype=np.float32)
                    control_rotation_raw = msg.get("control_rotation")
                    control_rotation = np.asarray(
                        offset[3:]
                        if control_rotation_raw is None
                        else control_rotation_raw,
                        dtype=np.float32,
                    )
                    try:
                        fraction_raw = msg.get("gripper_fraction")
                        fraction = (
                            None if fraction_raw is None else float(fraction_raw)
                        )
                    except (TypeError, ValueError):
                        continue
                    if (
                        offset.shape == (6,)
                        and np.isfinite(offset).all()
                        and control_rotation.shape == (3,)
                        and np.isfinite(control_rotation).all()
                        and (fraction is None or np.isfinite(fraction))
                    ):
                        self._pose_message_sequence += 1
                        if self._pose_release_required:
                            continue
                        self._ee_world_pose_offset = offset
                        self._ee_control_rotation_offset = control_rotation
                        self._ee_cartesian_delta = None
                        self._ee_pose_offset = None
                        self._ee_pose_active = True
                        self._gripper_fraction = (
                            None if fraction is None
                            else float(np.clip(fraction, 0.0, 1.0))
                        )
                        self._ee_axes.fill(0.0)
                        self._gripper_axis = 0.0
                        self._ee_velocity.fill(0.0)
                        self._gripper_velocity = 0.0
                        self._last_velocity_input_at = self._monotonic()
                elif msg.get("cmd") == "ee_pose_offset" and self.control_mode == "ee_delta":
                    offset = np.asarray(msg.get("offset", []), dtype=np.float32)
                    try:
                        gripper_velocity = float(msg.get("gripper_velocity", 0.0))
                        gripper_fraction_raw = msg.get("gripper_fraction")
                        gripper_fraction = (
                            None
                            if gripper_fraction_raw is None
                            else float(gripper_fraction_raw)
                        )
                    except (TypeError, ValueError):
                        continue
                    if (
                        offset.shape == (6,)
                        and np.isfinite(offset).all()
                        and np.isfinite(gripper_velocity)
                        and (
                            gripper_fraction is None
                            or np.isfinite(gripper_fraction)
                        )
                    ):
                        self._pose_message_sequence += 1
                        if self._pose_release_required:
                            continue
                        self._ee_pose_offset = offset
                        self._ee_cartesian_delta = None
                        self._ee_world_pose_offset = None
                        self._ee_control_rotation_offset = None
                        self._ee_pose_active = True
                        self._gripper_velocity = gripper_velocity
                        self._gripper_fraction = (
                            None
                            if gripper_fraction is None
                            else float(np.clip(gripper_fraction, 0.0, 1.0))
                        )
                        self._ee_axes.fill(0.0)
                        self._gripper_axis = 0.0
                        self._ee_velocity.fill(0.0)
                        self._last_velocity_input_at = self._monotonic()
                elif msg.get("cmd") == "home" and self.control_mode == "ee_delta":
                    self.stop_motion()
                    home_requested = True
                elif msg.get("cmd") == "stop":
                    self.stop_motion()
                    self._pose_release_required = False
                elif self._initialized and 0 <= joint < self._dof:
                    self._target[joint] += delta
            except asyncio.QueueEmpty:
                break

        await asyncio.sleep(0.005)

        if self.control_mode == "ee_delta":
            if home_requested:
                return TeleopAction(ee_pose_active=False, home_requested=True)
            if (
                self._last_velocity_input_at is not None
                and self._input_timeout_sec > 0.0
                and self._monotonic() - self._last_velocity_input_at
                > self._input_timeout_sec
            ):
                self.stop_motion()

            if self._ee_pose_active and self._ee_pose_offset is not None:
                rate_hz = float(self.control_rate_hz or 60)
                return TeleopAction(
                    ee_pose_offset=self._ee_pose_offset.copy(),
                    ee_pose_active=True,
                    gripper_delta=self._gripper_velocity / rate_hz,
                    gripper_fraction=self._gripper_fraction,
                )
            if self._ee_pose_active and self._ee_world_pose_offset is not None:
                return TeleopAction(
                    ee_world_pose_offset=self._ee_world_pose_offset.copy(),
                    ee_control_rotation_offset=(
                        self._ee_control_rotation_offset.copy()
                        if self._ee_control_rotation_offset is not None
                        else None
                    ),
                    ee_pose_active=True,
                    gripper_fraction=self._gripper_fraction,
                )
            if self._ee_pose_active and self._ee_cartesian_delta is not None:
                return TeleopAction(
                    ee_cartesian_delta=self._ee_cartesian_delta.copy(),
                    ee_pose_active=True,
                    gripper_fraction=self._gripper_fraction,
                )
            if self._last_velocity_input_at is not None:
                rate_hz = float(self.control_rate_hz or 60)
                delta = self._ee_velocity.copy() / rate_hz
                gripper_delta = self._gripper_velocity / rate_hz
            else:
                delta = self._ee_axes.copy()
                delta[:3] *= self._linear_step_m
                delta[3:] *= self._angular_step_rad
                gripper_delta = self._gripper_axis * self._gripper_step_rad
            return TeleopAction(
                ee_delta=delta,
                ee_pose_active=False,
                gripper_delta=gripper_delta,
            )

        # Before browser connects and sends "reset", return None so control loop skips
        if not self._initialized:
            return TeleopAction(target_joint_pos=None)

        return TeleopAction(target_joint_pos=self._target.copy())

    def stop_motion(self) -> None:
        """Clear held Cartesian axes on key-up, blur, or socket loss."""
        self._ee_axes.fill(0.0)
        self._gripper_axis = 0.0
        self._ee_velocity.fill(0.0)
        self._ee_pose_offset = None
        self._ee_cartesian_delta = None
        self._ee_world_pose_offset = None
        self._ee_control_rotation_offset = None
        self._ee_pose_active = False
        self._gripper_velocity = 0.0
        self._gripper_fraction = None
        self._last_velocity_input_at = None


class QuestRosTeleoperator(WebTeleoperator):
    """Clutch-relative EE pose endpoint used by the ROS 2 Quest bridge."""

    name = "quest_ros"

    def __init__(
        self,
        *,
        control_rate_hz: int = 60,
        input_timeout_sec: float = 0.3,
    ) -> None:
        super().__init__(
            control_mode="ee_delta",
            control_rate_hz=control_rate_hz,
            input_timeout_sec=input_timeout_sec,
        )
