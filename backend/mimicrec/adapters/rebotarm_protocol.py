"""Wire-protocol constants for the reBotArm safety daemon ZMQ bridge.

These names are duplicated verbatim in scripts/rebotarm_daemon/server.py
(which lives in a separate Python 3.10 venv and cannot import this module
at runtime). Keep them in sync.
"""
from __future__ import annotations

# Commands (request 'cmd' field)
CMD_CONNECT = "connect"
CMD_DISCONNECT = "disconnect"
CMD_READ_STATE = "read_state"
CMD_SEND_COMMAND = "send_command"
CMD_SET_MODE = "set_mode"
CMD_HEARTBEAT = "heartbeat"
CMD_ESTOP = "estop"
CMD_CLEAR_ESTOP = "clear_estop"
CMD_GET_SAFETY_STATUS = "get_safety_status"

# Safety state values (in read_state and get_safety_status responses)
SAFETY_OK = "ok"
SAFETY_WARN = "warn"
SAFETY_ESTOP = "estop"
SAFETY_HEARTBEAT_TIMEOUT = "heartbeat_timeout"
SAFETY_THERMAL_FAULT = "thermal_fault"
SAFETY_TORQUE_FAULT = "torque_fault"

# Mode values
MODE_POSITION = "position"
MODE_GRAVITY_COMP = "gravity_comp"

DEFAULT_ZMQ_ADDRESS = "tcp://localhost:5558"
