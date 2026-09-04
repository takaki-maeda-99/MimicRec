"""Hardware-fault recovery tests for the vendored RobotArm wrapper."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
ARM_MODULE = (
    REPO_ROOT / "third_party/reBotArm_control_py/reBotArm_control_py/actuator/arm.py"
)


class FakeCallError(Exception):
    pass


@pytest.fixture(scope="module")
def arm_module():
    motorbridge = types.ModuleType("motorbridge")
    motorbridge.Controller = object
    motorbridge.Mode = types.SimpleNamespace(MIT="mit", POS_VEL="pos_vel", VEL="vel")
    motorbridge.CallError = FakeCallError
    previous = sys.modules.get("motorbridge")
    sys.modules["motorbridge"] = motorbridge
    try:
        spec = importlib.util.spec_from_file_location(
            "rebotarm_arm_clear_fault_test_module", ARM_MODULE
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop("rebotarm_arm_clear_fault_test_module", None)
        if previous is None:
            sys.modules.pop("motorbridge", None)
        else:
            sys.modules["motorbridge"] = previous


class FakeMotor:
    def __init__(self, *, failure=None):
        self.failure = failure
        self.calls = []

    def clear_error(self):
        self.calls.append("clear_error")
        if self.failure:
            raise self.failure

    def enable(self):
        self.calls.append("enable")

    def ensure_mode(self, mode, timeout_ms):
        self.calls.append(("ensure_mode", mode, timeout_ms))

    def get_state(self):
        return types.SimpleNamespace(status_code=1)


def test_clear_faults_reports_each_joint_and_restores_mit(arm_module):
    arm = arm_module.RobotArm.__new__(arm_module.RobotArm)
    arm._mode = "mit"
    arm._joints = [
        types.SimpleNamespace(name="joint1"),
        types.SimpleNamespace(name="joint2"),
    ]
    good = FakeMotor()
    bad = FakeMotor(failure=FakeCallError("still faulted"))
    arm._motor_map = {"joint1": good, "joint2": bad}
    arm._request_and_poll = lambda: None
    arm._poll_all = lambda: None

    result = arm.clear_faults()

    assert result["joint1"] == {"ok": True, "status_code": 1}
    assert result["joint2"]["ok"] is False
    assert "still faulted" in result["joint2"]["error"]
    assert good.calls == [
        "clear_error",
        "enable",
        ("ensure_mode", "mit", 1000),
    ]
    assert bad.calls == ["clear_error"]
