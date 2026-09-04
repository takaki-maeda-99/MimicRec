"""Torque-limit tests for the vendored reBotArm gripper wrapper."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
GRIPPER_MODULE = (
    REPO_ROOT
    / "third_party/reBotArm_control_py/reBotArm_control_py/actuator/gripper.py"
)
GRIPPER_CONFIG = REPO_ROOT / "configs/rebotarm/gripper.yaml"


class FakeCallError(Exception):
    pass


class FakeControllerType:
    pass


@pytest.fixture(scope="module")
def gripper_module():
    motorbridge = types.ModuleType("motorbridge")
    motorbridge.Controller = FakeControllerType
    motorbridge.Mode = types.SimpleNamespace(MIT="mit", POS_VEL="pos_vel", VEL="vel")
    motorbridge.CallError = FakeCallError

    previous = sys.modules.get("motorbridge")
    sys.modules["motorbridge"] = motorbridge
    try:
        spec = importlib.util.spec_from_file_location(
            "rebotarm_gripper_torque_test_module", GRIPPER_MODULE)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop("rebotarm_gripper_torque_test_module", None)
        if previous is None:
            sys.modules.pop("motorbridge", None)
        else:
            sys.modules["motorbridge"] = previous


class FakeMotor:
    def __init__(
        self,
        *,
        pos=-0.5,
        vel=0.0,
        state_available=True,
        feedback_after_polls=None,
    ):
        self.state = (
            types.SimpleNamespace(pos=pos, vel=vel, torq=0.0, status_code=1)
            if state_available
            else None
        )
        self.mit_commands = []
        self.feedback_after_polls = feedback_after_polls
        self.feedback_pending = False
        self.feedback_polls = 0
        self.clear_error_calls = 0
        self.enable_calls = 0
        self.ensured_modes = []

    def get_state(self):
        return self.state

    def send_mit(self, pos, vel, kp, kd, tau):
        self.mit_commands.append((pos, vel, kp, kd, tau))

    def request_feedback(self):
        self.feedback_pending = True
        self.feedback_polls = 0

    def clear_error(self):
        self.clear_error_calls += 1

    def enable(self):
        self.enable_calls += 1

    def ensure_mode(self, mode, timeout_ms):
        self.ensured_modes.append((mode, timeout_ms))


class FakeController:
    def __init__(self, motor):
        self.motor = motor

    def add_damiao_motor(self, *args):
        return self.motor

    def poll_feedback_once(self):
        motor = self.motor
        if not motor.feedback_pending or motor.feedback_after_polls is None:
            return
        motor.feedback_polls += 1
        if motor.feedback_polls >= motor.feedback_after_polls:
            motor.feedback_pending = False
            if motor.state is not None and motor.mit_commands:
                motor.state.pos = motor.mit_commands[-1][0]
                motor.state.vel = motor.mit_commands[-1][1]


def make_gripper(module, motor):
    return module.Gripper(
        cfg_path=str(GRIPPER_CONFIG), controller=FakeController(motor))


def estimated_torque(command, current_pos, current_vel):
    pos, vel, kp, kd, tau = command
    return kp * (pos - current_pos) + kd * (vel - current_vel) + tau


def test_project_config_loads_safe_limit(gripper_module):
    cfg = gripper_module.load_cfg(str(GRIPPER_CONFIG))["gripper"]
    assert cfg.slip_torque_nm == pytest.approx(3.88)
    assert cfg.safe_max_nm == pytest.approx(2.5)


def test_position_pd_command_is_limited_to_safe_max(gripper_module):
    motor = FakeMotor(pos=-0.5, vel=0.0)
    gripper = make_gripper(gripper_module, motor)

    gripper.mit(pos=0.0, vel=0.0, kp=8.0, kd=1.0, tau=0.0)

    command = motor.mit_commands[-1]
    assert command[0] == pytest.approx(-0.1875)
    assert estimated_torque(command, -0.5, 0.0) == pytest.approx(2.5)


def test_position_limit_advances_after_delayed_feedback(gripper_module):
    motor = FakeMotor(pos=-0.5, vel=0.0, feedback_after_polls=2)
    gripper = make_gripper(gripper_module, motor)

    gripper.mit(pos=0.0, vel=0.0, kp=8.0, kd=1.0, tau=0.0)
    assert motor.mit_commands[-1][0] == pytest.approx(-0.1875)

    gripper.mit(pos=0.0, vel=0.0, kp=8.0, kd=1.0, tau=0.0)

    assert motor.mit_commands[-1][0] == pytest.approx(0.0)


def test_torque_only_command_is_limited(gripper_module):
    motor = FakeMotor(pos=0.0, vel=0.0)
    gripper = make_gripper(gripper_module, motor)

    gripper.mit(pos=0.0, vel=0.0, kp=0.0, kd=0.0, tau=4.0)

    assert motor.mit_commands[-1][-1] == pytest.approx(2.5)


def test_missing_feedback_fails_closed_for_one_cycle(gripper_module):
    motor = FakeMotor(state_available=False)
    gripper = make_gripper(gripper_module, motor)

    gripper.mit(pos=10.0, vel=10.0, kp=8.0, kd=1.0, tau=4.0)

    _, _, kp, kd, tau = motor.mit_commands[-1]
    assert (kp, kd, tau) == pytest.approx((0.0, 0.0, 2.5))


def test_limit_can_be_explicitly_disabled(gripper_module):
    motor = FakeMotor(pos=-0.5, vel=0.0)
    gripper = make_gripper(gripper_module, motor)
    gripper.set_tau_limit_nm(None)

    gripper.mit(pos=0.0, vel=0.0, kp=8.0, kd=1.0, tau=0.0)

    assert motor.mit_commands[-1] == pytest.approx((0.0, 0.0, 8.0, 1.0, 0.0))


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("mode_pos_vel", ()),
        ("mode_vel", ()),
        ("pos_vel", (0.0,)),
        ("set_vel", (0.0,)),
    ],
)
def test_limit_rejects_modes_that_cannot_enforce_torque(
    gripper_module, method, args,
):
    gripper = make_gripper(gripper_module, FakeMotor())
    with pytest.raises(RuntimeError, match="cannot enforce"):
        getattr(gripper, method)(*args)


@pytest.mark.parametrize(
    "value", [0.0, -1.0, 4.0, float("nan"), float("inf")])
def test_invalid_runtime_limit_is_rejected(gripper_module, value):
    gripper = make_gripper(gripper_module, FakeMotor())
    with pytest.raises(ValueError):
        gripper.set_tau_limit_nm(value)


def test_safe_limit_must_not_exceed_slip_limit(gripper_module, tmp_path):
    cfg_path = tmp_path / "gripper.yaml"
    cfg_path.write_text(
        """
channel: /dev/null
gripper:
  - name: gripper
    motor_id: 7
    feedback_id: 23
    model: "4310"
    torque_limits:
      slip_torque_nm: 2.0
      safe_max_nm: 2.5
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must not exceed"):
        gripper_module.load_cfg(str(cfg_path))


def test_clear_fault_clears_reenables_and_restores_mode(gripper_module):
    motor = FakeMotor(pos=0.0, vel=0.0)
    gripper = make_gripper(gripper_module, motor)

    result = gripper.clear_fault()

    assert result == {"ok": True, "status_code": 1}
    assert motor.clear_error_calls == 1
    assert motor.enable_calls == 1
    assert motor.ensured_modes == [("mit", 1000)]
