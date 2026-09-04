"""ROS 2 node connecting Unity Quest topics to a MimicRec session."""

from __future__ import annotations

import signal
import threading
import time

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.exceptions import ParameterUninitializedException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Joy
from tf2_msgs.msg import TFMessage

from .motion import (
    HoldActionLatch,
    Pose,
    PoseOffsetInterpolator,
    QuestMotionMapper,
    compose_pose,
)
from .transport import MimicRecWebSocketTransport


class MimicRecQuestBridge(Node):
    def __init__(self) -> None:
        super().__init__("mimicrec_quest_bridge")
        self.declare_parameter("mimicrec_url", "ws://127.0.0.1:8000")
        self.declare_parameter("motion_channel", "right")
        self.declare_parameter("pose_source", "tf")
        self.declare_parameter("tf_topic", "/tf")
        self.declare_parameter("controller_frame", "hand_right")
        # unity_ros_teleoperation's tracking-world TF is named vr_origin by
        # default. This ROS frame is emitted under the canonical MotionStep
        # label WORLD; the two names do not need to be identical.
        self.declare_parameter("world_frame", "vr_origin")
        self.declare_parameter("motion_frame", "ee_local")
        self.declare_parameter("pose_topic", "/quest/pose/right")
        self.declare_parameter("joy_topic", "/quest/joystick")
        self.declare_parameter("deadman_axis_index", 7)
        self.declare_parameter("deadman_button_index", -1)
        self.declare_parameter("deadman_threshold", 0.5)
        self.declare_parameter("gripper_trigger_axis_index", 5)
        self.declare_parameter("gripper_trigger_deadzone", 0.03)
        self.declare_parameter("home_button_index", 1)
        self.declare_parameter("home_hold_sec", 0.5)
        self.declare_parameter("input_timeout_sec", 0.25)
        self.declare_parameter(
            "controller_to_eef_rotation",
            [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        )
        self.declare_parameter(
            "world_axis_rotation",
            [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        )
        self.declare_parameter("translation_scale", 1.0)
        self.declare_parameter("rotation_scale", 1.0)
        self.declare_parameter("max_linear_offset_m", 0.5)
        self.declare_parameter("max_angular_offset_rad", 3.141592653589793)
        self.declare_parameter("linear_deadband_m", 0.0005)
        self.declare_parameter("angular_deadband_rad", 0.005)
        self.declare_parameter("command_rate_hz", 60.0)
        self.declare_parameter("interpolation_delay_sec", 0.025)
        self.declare_parameter("smoothing_time_constant_sec", 0.0)
        self.declare_parameter("camera_names", ["front", "wrist"])
        self.declare_parameter("camera_topic_prefix", "/mimicrec/cameras")

        def value(name: str):
            return self.get_parameter(name).value
        self._controller_frame = str(value("controller_frame"))
        self._world_frame = str(value("world_frame"))
        self._motion_frame = str(value("motion_frame"))
        self._deadman_axis_index = int(value("deadman_axis_index"))
        self._deadman_button_index = int(value("deadman_button_index"))
        self._deadman_threshold = float(value("deadman_threshold"))
        self._gripper_trigger_axis_index = int(value("gripper_trigger_axis_index"))
        self._gripper_trigger_deadzone = float(value("gripper_trigger_deadzone"))
        self._home_button_index = int(value("home_button_index"))
        self._home_hold_sec = float(value("home_hold_sec"))
        self._input_timeout = float(value("input_timeout_sec"))
        self._gripper_fraction = 0.0
        self._home_latch = HoldActionLatch(self._home_hold_sec)
        command_rate_hz = float(value("command_rate_hz"))
        if command_rate_hz <= 0.0:
            raise ValueError("command_rate_hz must be > 0")
        self._interpolator = PoseOffsetInterpolator(
            float(value("interpolation_delay_sec")),
            float(value("smoothing_time_constant_sec")),
        )
        self._last_joy_at: float | None = None
        self._last_pose_at: float | None = None
        self._tf_edges: dict[str, tuple[str, Pose]] = {}

        self._motion = QuestMotionMapper(
            controller_to_eef_rotation=value("controller_to_eef_rotation"),
            translation_scale=float(value("translation_scale")),
            rotation_scale=float(value("rotation_scale")),
            max_linear_offset_m=float(value("max_linear_offset_m")),
            max_angular_offset_rad=float(value("max_angular_offset_rad")),
            linear_deadband_m=float(value("linear_deadband_m")),
            angular_deadband_rad=float(value("angular_deadband_rad")),
            output_frame=self._motion_frame,
            world_axis_rotation=value("world_axis_rotation"),
        )

        self._camera_lock = threading.Lock()
        self._transport_transition = threading.Event()
        self._camera_frames: dict[str, tuple[bytes, int]] = {}
        self._camera_published_at: dict[str, int] = {}
        try:
            camera_names = [str(name) for name in value("camera_names")]
        except ParameterUninitializedException:
            # ROS 2 represents an empty YAML sequence as a type-less, unset
            # parameter.  A motion-only bridge (for example the left Quest
            # controller) deliberately uses ``camera_names: []``.
            camera_names = []
        topic_prefix = str(value("camera_topic_prefix")).rstrip("/")
        self._camera_publishers = {
            name: self.create_publisher(
                CompressedImage,
                f"{topic_prefix}/{name}/image_raw/compressed",
                qos_profile_sensor_data,
            )
            for name in camera_names
        }

        self._transport = MimicRecWebSocketTransport(
            base_url=str(value("mimicrec_url")),
            camera_names=camera_names,
            on_camera=self._on_camera,
            on_teleop_state=self._on_teleop_state,
            motion_channel=str(value("motion_channel")),
        )
        self._transport.start()

        pose_source = str(value("pose_source"))
        if pose_source == "tf":
            self.create_subscription(
                TFMessage,
                str(value("tf_topic")),
                self._on_tf,
                qos_profile_sensor_data,
            )
        elif pose_source == "pose_stamped":
            self.create_subscription(
                PoseStamped,
                str(value("pose_topic")),
                self._on_pose_stamped,
                qos_profile_sensor_data,
            )
        else:
            raise ValueError("pose_source must be 'tf' or 'pose_stamped'")
        self.create_subscription(
            Joy,
            str(value("joy_topic")),
            self._on_joy,
            qos_profile_sensor_data,
        )
        self.create_timer(0.02, self._publish_cameras)
        self.create_timer(1.0 / command_rate_hz, self._publish_motion)
        self.create_timer(0.05, self._watchdog)
        self.get_logger().info(
            f"Quest bridge ready: source={pose_source} "
            f"frame={self._controller_frame} rate={command_rate_hz:g}Hz "
            f"cameras={camera_names}"
        )

    @staticmethod
    def _axis(values, index: int) -> float:
        return float(values[index]) if 0 <= index < len(values) else 0.0

    @staticmethod
    def _button(values, index: int) -> bool:
        return bool(values[index]) if 0 <= index < len(values) else False

    def _on_joy(self, message: Joy) -> None:
        now = time.monotonic()
        self._last_joy_at = now
        if self._deadman_button_index >= 0:
            active = self._button(message.buttons, self._deadman_button_index)
        else:
            active = (
                self._axis(message.axes, self._deadman_axis_index)
                >= self._deadman_threshold
            )
        changed = self._motion.set_active(active)
        if changed:
            self._interpolator.reset()
        trigger = max(
            0.0, min(1.0, self._axis(message.axes, self._gripper_trigger_axis_index))
        )
        if trigger <= self._gripper_trigger_deadzone:
            self._gripper_fraction = 0.0
        else:
            usable = max(1e-6, 1.0 - self._gripper_trigger_deadzone)
            self._gripper_fraction = min(
                1.0, (trigger - self._gripper_trigger_deadzone) / usable
            )

        if self._home_latch.update(
            pressed=self._button(message.buttons, self._home_button_index),
            allowed=not active,
            now=now,
        ):
            if not self._transport.send_home():
                self.get_logger().warning(
                    "Home request ignored because MimicRec teleop is disconnected"
                )
        if changed and not active:
            self._transport.send_stop()

    def _on_tf(self, message: TFMessage) -> None:
        child = self._controller_frame.lstrip("/")
        controller_updated = False
        for transform in message.transforms:
            transform_child = transform.child_frame_id.lstrip("/")
            translation = transform.transform.translation
            rotation = transform.transform.rotation
            self._tf_edges[transform_child] = (
                transform.header.frame_id.lstrip("/"),
                Pose(
                    position=(translation.x, translation.y, translation.z),
                    orientation_xyzw=(rotation.x, rotation.y, rotation.z, rotation.w),
                ),
            )
            if transform_child == child:
                controller_updated = True

        # /tf is shared by the headset and both controllers. Previously every
        # unrelated TF message re-stamped the cached controller pose as a new
        # sample. That produced a repeated-hold/catch-up pattern at the IK
        # input even when the physical controller moved smoothly. Only emit a
        # sample when this controller's own edge was updated in this message.
        if not controller_updated:
            return
        world = self._world_frame.lstrip("/")
        if child not in self._tf_edges:
            return
        parent, pose = self._tf_edges[child]
        visited = {child}
        while parent != world:
            if parent in visited or parent not in self._tf_edges:
                return
            visited.add(parent)
            grandparent, parent_pose = self._tf_edges[parent]
            pose = compose_pose(parent_pose, pose)
            parent = grandparent
        self._handle_pose(pose)

    def _on_pose_stamped(self, message: PoseStamped) -> None:
        position = message.pose.position
        orientation = message.pose.orientation
        self._handle_pose(
            Pose(
                position=(position.x, position.y, position.z),
                orientation_xyzw=(
                    orientation.x,
                    orientation.y,
                    orientation.z,
                    orientation.w,
                ),
            )
        )

    def _handle_pose(self, pose: Pose) -> None:
        now = time.monotonic()
        self._last_pose_at = now
        command = self._motion.update_pose(pose)
        if command is not None:
            self._interpolator.add(now, command)

    def _publish_motion(self) -> None:
        if not self._motion.active:
            return
        command = self._interpolator.sample(time.monotonic())
        if command is not None:
            if self._motion_frame == "world":
                self._transport.send_world_pose_offset(
                    command.as_list(),
                    (
                        command.control_rotation_rotvec
                        or command.rotation_rotvec
                    ),
                    self._gripper_fraction,
                )
            else:
                self._transport.send_pose_offset(
                    command.as_list(), self._gripper_fraction
                )

    def _watchdog(self) -> None:
        if self._transport_transition.is_set():
            self._transport_transition.clear()
            self._motion.fault_stop()
            self._interpolator.reset()
            self._transport.send_stop()
            self.get_logger().warning(
                "MimicRec teleop connection changed; release and re-press "
                "the deadman grip"
            )
        if not self._motion.active:
            return
        now = time.monotonic()
        joy_stale = self._last_joy_at is None or now - self._last_joy_at > self._input_timeout
        pose_stale = self._last_pose_at is None or now - self._last_pose_at > self._input_timeout
        if joy_stale or pose_stale:
            self._motion.fault_stop()
            self._interpolator.reset()
            self._transport.send_stop()
            self.get_logger().warning("Quest input timed out; motion stopped")

    def _on_teleop_state(self, _connected: bool) -> None:
        self._transport_transition.set()

    def _on_camera(self, camera_name: str, jpeg: bytes, timestamp_ns: int) -> None:
        with self._camera_lock:
            self._camera_frames[camera_name] = (jpeg, timestamp_ns)

    def _publish_cameras(self) -> None:
        with self._camera_lock:
            frames = dict(self._camera_frames)
        for camera_name, (jpeg, timestamp_ns) in frames.items():
            if self._camera_published_at.get(camera_name) == timestamp_ns:
                continue
            message = CompressedImage()
            message.header.stamp.sec = timestamp_ns // 1_000_000_000
            message.header.stamp.nanosec = timestamp_ns % 1_000_000_000
            message.header.frame_id = camera_name
            message.format = "jpeg"
            message.data = jpeg
            self._camera_publishers[camera_name].publish(message)
            self._camera_published_at[camera_name] = timestamp_ns

    def destroy_node(self):
        self._motion.set_active(False)
        self._transport.stop()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MimicRecQuestBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # ros2 launch forwards SIGINT after the terminal already delivered it
        # to this process group. Ignore that second signal while the WebSocket
        # worker performs its bounded shutdown.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
