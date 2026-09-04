"""Wire protocol shared by the SO-101 daemon client and tests."""

CMD_CONNECT = "connect"
CMD_DISCONNECT = "disconnect"
CMD_READ_STATE = "read_state"
CMD_SEND_COMMAND = "send_command"
CMD_SEND_GRIPPER_COMMAND = "send_gripper_command"
CMD_SET_MODE = "set_mode"
CMD_HEARTBEAT = "heartbeat"
CMD_GET_STATUS = "get_status"

MODE_POSITION = "position"
MODE_TORQUE_OFF = "torque_off"

DEFAULT_ZMQ_ADDRESS = "tcp://localhost:5559"


def validate_reply(reply: object) -> dict:
    if not isinstance(reply, dict) or "ok" not in reply:
        raise ValueError(f"malformed SO-101 daemon reply: {reply!r}")
    return reply
