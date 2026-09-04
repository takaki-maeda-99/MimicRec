"""The only module in the SO-101 daemon that imports and touches LeRobot."""
from __future__ import annotations

from pathlib import Path


ARM_JOINT_NAMES = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
)
ALL_JOINT_NAMES = (*ARM_JOINT_NAMES, "gripper")


class SO101Hardware:
    def __init__(
        self,
        *,
        port: str,
        arm_id: str,
        arm_p_coefficient: int = 32,
        arm_p_coefficients: dict[str, int] | None = None,
        arm_i_coefficient: int = 0,
        gripper_p_coefficient: int = 16,
        gripper_i_coefficient: int = 0,
        gripper_d_coefficient: int = 32,
        arm_acceleration: int = 254,
        arm_goal_velocity: int = 0,
    ) -> None:
        self.port = port
        self.arm_id = arm_id
        self.arm_p_coefficient = int(arm_p_coefficient)
        self.arm_p_coefficients = dict(arm_p_coefficients or {})
        self.arm_i_coefficient = int(arm_i_coefficient)
        self.gripper_p_coefficient = int(gripper_p_coefficient)
        self.gripper_i_coefficient = int(gripper_i_coefficient)
        self.gripper_d_coefficient = int(gripper_d_coefficient)
        self.arm_acceleration = int(arm_acceleration)
        self.arm_goal_velocity = int(arm_goal_velocity)
        self.follower = None
        self._read_count = 0
        self._voltage_raw: dict[str, int] = {}

    def connect(self) -> None:
        from lerobot.robots.so_follower.config_so_follower import (
            SOFollowerRobotConfig,
        )
        from lerobot.robots.so_follower.so_follower import SO101Follower

        follower = SO101Follower(
            SOFollowerRobotConfig(port=self.port, id=self.arm_id, use_degrees=True)
        )
        calibration_path: Path = follower.calibration_fpath
        if not calibration_path.is_file():
            raise RuntimeError(
                f"SO-101 calibration is missing: {calibration_path}. "
                f"Run scripts/calibrate_so101.py --port {self.port} "
                f"--id {self.arm_id} --type follower"
            )
        follower.connect(calibrate=False)
        if not follower.is_calibrated:
            follower.bus.write_calibration(follower.calibration)
        if not follower.is_calibrated:
            follower.disconnect()
            raise RuntimeError(
                f"SO-101 motors do not match calibration {calibration_path}"
            )
        # LeRobot intentionally lowers every SO follower motor's P gain to 16
        # in ``configure()``. That is too compliant for Cartesian holding on
        # this arm: under gravity the elbow can remain almost two degrees away
        # from its goal indefinitely. Apply the explicitly measured arm gains
        # here while leaving gripper PID and torque/current protection alone.
        # Leave torque disabled after configuration. The generic
        # ``torque_disabled()`` context re-enables every motor on exit, which
        # is both unnecessary here and can fail on a transient supply dip
        # before the daemon has seeded a safe hold target.
        follower.bus.disable_torque()
        for name in ARM_JOINT_NAMES:
            follower.bus.write(
                "P_Coefficient",
                name,
                self.arm_p_coefficients.get(
                    name, self.arm_p_coefficient
                ),
            )
            follower.bus.write(
                "I_Coefficient", name, self.arm_i_coefficient
            )
            # SOFollower.configure() forces the maximum value 254 for
            # demonstration-speed motion. Restore an explicit arm profile
            # so streamed Cartesian goals can use the STS3215's built-in
            # acceleration start/stop.
            follower.bus.write(
                "Acceleration", name, self.arm_acceleration
            )
            follower.bus.write(
                "Goal_Velocity", name, self.arm_goal_velocity
            )
        # Keep the gripper's LeRobot torque/current protection intact while
        # allowing its position-loop gains to be tuned independently of the
        # arm. The default P=16 often stalls in the final few raw units before
        # fully closed because it cannot overcome linkage friction.
        follower.bus.write(
            "P_Coefficient", "gripper", self.gripper_p_coefficient
        )
        follower.bus.write(
            "I_Coefficient", "gripper", self.gripper_i_coefficient
        )
        follower.bus.write(
            "D_Coefficient", "gripper", self.gripper_d_coefficient
        )
        self.follower = follower
        self._read_count = 0
        self._voltage_raw = {}

    def disconnect(self) -> None:
        if self.follower is not None:
            self.follower.disconnect()
            self.follower = None

    def read(self) -> dict[str, float]:
        if self.follower is None:
            raise RuntimeError("SO-101 hardware is not connected")
        observation = self.follower.get_observation()
        # A 5 V SO-101 supply can dip only while several joints move. Sample
        # the bus voltage at ~10 Hz without doubling every 50 Hz state read.
        if self._read_count % 5 == 0:
            self._voltage_raw = {
                name: int(value)
                for name, value in self.follower.bus.sync_read(
                    "Present_Voltage", normalize=False
                ).items()
            }
        self._read_count += 1
        observation["_voltage_raw"] = dict(self._voltage_raw)
        return observation

    def send(self, positions: dict[str, float]) -> None:
        if self.follower is None:
            raise RuntimeError("SO-101 hardware is not connected")
        self.follower.send_action(
            {f"{name}.pos": float(value) for name, value in positions.items()}
        )

    def disable_torque(self) -> None:
        if self.follower is not None:
            self.follower.bus.disable_torque()

    def hold_current_and_enable_torque(self) -> dict[str, float]:
        if self.follower is None:
            raise RuntimeError("SO-101 hardware is not connected")
        observation = self.read()
        positions = {
            name: float(observation[f"{name}.pos"])
            for name in ALL_JOINT_NAMES
        }
        # Seed Goal_Position while torque is disabled. This prevents enabling
        # against a stale goal retained from an earlier client lease.
        self.send(positions)
        self.follower.bus.enable_torque()
        return observation
