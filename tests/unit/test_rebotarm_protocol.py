from mimicrec.adapters import rebotarm_protocol as p


def test_command_names_are_stable_strings():
    assert p.CMD_CONNECT == "connect"
    assert p.CMD_DISCONNECT == "disconnect"
    assert p.CMD_READ_STATE == "read_state"
    assert p.CMD_SEND_COMMAND == "send_command"
    assert p.CMD_SET_MODE == "set_mode"
    assert p.CMD_HEARTBEAT == "heartbeat"
    assert p.CMD_ESTOP == "estop"
    assert p.CMD_CLEAR_ESTOP == "clear_estop"
    assert p.CMD_GET_SAFETY_STATUS == "get_safety_status"


def test_safety_states_are_stable_strings():
    assert p.SAFETY_OK == "ok"
    assert p.SAFETY_WARN == "warn"
    assert p.SAFETY_ESTOP == "estop"
    assert p.SAFETY_HEARTBEAT_TIMEOUT == "heartbeat_timeout"
    assert p.SAFETY_THERMAL_FAULT == "thermal_fault"
    assert p.SAFETY_TORQUE_FAULT == "torque_fault"


def test_modes_match_robot_mode_values():
    from mimicrec.adapters.robot import RobotMode
    assert p.MODE_POSITION == RobotMode.POSITION.value
    assert p.MODE_GRAVITY_COMP == RobotMode.GRAVITY_COMP.value
