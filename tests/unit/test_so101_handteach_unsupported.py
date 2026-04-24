import pytest

from mimicrec.adapters.robot import RobotMode
from mimicrec.adapters.so101 import SO101Adapter
from mimicrec.errors import HandTeachNotSupportedError
from mimicrec.session.lifecycle import StartSessionRequestDomain, precheck_start
from mimicrec.types import SessionMode


async def test_set_mode_gravity_comp_raises_unsupported():
    a = SO101Adapter(port="/dev/null")
    with pytest.raises(HandTeachNotSupportedError) as e:
        await a.set_mode(RobotMode.GRAVITY_COMP)
    assert "so101" in str(e.value).lower()


async def test_position_mode_is_allowed():
    a = SO101Adapter(port="/dev/null")
    await a.set_mode(RobotMode.POSITION)


def test_precheck_rejects_so101_handteach():
    a = SO101Adapter(port="/dev/null")
    req = StartSessionRequestDomain(robot=a, mode=SessionMode.HAND_TEACH)
    with pytest.raises(HandTeachNotSupportedError):
        precheck_start(req)


def test_precheck_accepts_so101_teleop():
    a = SO101Adapter(port="/dev/null")
    req = StartSessionRequestDomain(robot=a, mode=SessionMode.TELEOP)
    precheck_start(req)
