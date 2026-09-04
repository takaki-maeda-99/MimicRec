from __future__ import annotations

import zmq

from so101_daemon.config import SO101DaemonConfig
from so101_daemon.core import SO101DaemonCore
from so101_daemon.hardware import SO101Hardware


def run_server(config: SO101DaemonConfig) -> None:
    hardware = SO101Hardware(
        port=config.port,
        arm_id=config.arm_id,
        arm_p_coefficient=config.arm_p_coefficient,
        arm_p_coefficients=config.arm_p_coefficients,
        arm_i_coefficient=config.arm_i_coefficient,
        gripper_p_coefficient=config.gripper_p_coefficient,
        gripper_i_coefficient=config.gripper_i_coefficient,
        gripper_d_coefficient=config.gripper_d_coefficient,
        arm_acceleration=config.arm_acceleration,
        arm_goal_velocity=config.arm_goal_velocity,
    )
    core = SO101DaemonCore(config, hardware)
    context = zmq.Context()
    socket = context.socket(zmq.REP)
    socket.setsockopt(zmq.LINGER, 0)
    try:
        core.start()
        socket.bind(config.zmq_address)
        print(
            f"[so101-daemon] ready on {config.zmq_address} "
            f"({config.port}, id={config.arm_id})",
            flush=True,
        )
        while True:
            message = socket.recv_json()
            socket.send_json(core.handle(message))
    except KeyboardInterrupt:
        pass
    finally:
        core.stop()
        socket.close(linger=0)
        context.term()
