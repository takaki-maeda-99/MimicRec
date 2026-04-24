from __future__ import annotations
from mimicrec.types import RobotCommand, RobotState, TeleopAction


class IdentityMapper:
    def map(self, action: TeleopAction, robot_state: RobotState) -> RobotCommand:
        assert action.target_joint_pos is not None, "IdentityMapper requires joint-pos teleop"
        return RobotCommand(q=action.target_joint_pos.copy())
