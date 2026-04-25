#!/usr/bin/env python
"""Isaac Sim bridge server for MimicRec.

    ~/isaacsim/python.sh scripts/sim_bridge_isaacsim.py
    ~/isaacsim/python.sh scripts/sim_bridge_isaacsim.py --robot franka --headless
    ~/isaacsim/python.sh scripts/sim_bridge_isaacsim.py --robot usd:/path/to/scene.usd
"""
from __future__ import annotations

import argparse
import threading
import time

import numpy as np


def main():
    parser = argparse.ArgumentParser(description="Isaac Sim bridge for MimicRec")
    parser.add_argument("--robot", default="franka")
    parser.add_argument("--robot_prim", default=None)
    parser.add_argument("--robot_port", type=int, default=5556)
    parser.add_argument("--camera_port", type=int, default=5557)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    from isaacsim import SimulationApp
    sim_app = SimulationApp({"headless": args.headless})

    from isaacsim.core.api import World
    from isaacsim.storage.native import get_assets_root_path
    import isaacsim.core.utils.stage as stage_utils
    from isaacsim.core.prims import SingleArticulation

    world = World(stage_units_in_meters=1.0)
    world.scene.add_default_ground_plane()
    assets = get_assets_root_path()

    if args.robot == "franka":
        usd = assets + "/Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd"
        prim_path = args.robot_prim or "/World/Franka"
        stage_utils.add_reference_to_stage(usd, prim_path)
    elif args.robot.startswith("usd:"):
        import omni.usd
        omni.usd.get_context().open_stage(args.robot[4:])
        prim_path = args.robot_prim or "/World/Robot"
    else:
        print(f"Unknown robot: {args.robot}")
        return

    world.reset()
    robot = SingleArticulation(prim_path=prim_path, name="robot")
    robot.initialize()
    dof = robot.num_dof
    joint_names = list(robot.dof_names)

    import zmq
    ctx = zmq.Context()

    robot_sock = ctx.socket(zmq.REP)
    robot_sock.bind(f"tcp://*:{args.robot_port}")

    cam_sock = ctx.socket(zmq.PUB)
    cam_sock.bind(f"tcp://*:{args.camera_port}")

    # Shared state protected by lock
    lock = threading.Lock()
    latest_pos = np.zeros(dof)
    latest_vel = np.zeros(dof)
    pending_cmd = [None]  # mutable container for thread-safe exchange
    running = [True]

    # ZMQ handler thread — responds instantly, never blocked by world.step()
    def zmq_thread():
        while running[0]:
            try:
                msg = robot_sock.recv_json(flags=zmq.NOBLOCK)
            except zmq.Again:
                time.sleep(0.001)
                continue

            cmd = msg.get("cmd")
            if cmd == "connect":
                robot_sock.send_json({"ok": True, "dof": dof, "joint_names": joint_names})
            elif cmd == "read_state":
                with lock:
                    p, v = latest_pos.tolist(), latest_vel.tolist()
                robot_sock.send_json({
                    "joint_pos": p,
                    "joint_vel": v,
                    "joint_effort": [0.0] * dof,
                })
            elif cmd == "send_command":
                q = msg.get("q", [])
                with lock:
                    pending_cmd[0] = np.array(q, dtype=np.float32)
                robot_sock.send_json({"ok": True})
            elif cmd == "set_mode":
                robot_sock.send_json({"ok": True})
            elif cmd == "disconnect":
                robot_sock.send_json({"ok": True})
            elif cmd == "shutdown":
                robot_sock.send_json({"ok": True})
                running[0] = False
            else:
                robot_sock.send_json({"ok": True})

    t = threading.Thread(target=zmq_thread, daemon=True)
    t.start()

    # Write ready signal
    open("/tmp/mimicrec_bridge_ready", "w").write("1")
    import sys
    sys.stderr.write(f"BRIDGE READY: DOF={dof}, joints={joint_names}\n")

    try:
        while running[0] and sim_app.is_running():
            world.step(render=not args.headless)

            # Update latest state
            pos = robot.get_joint_positions()
            vel = robot.get_joint_velocities()
            with lock:
                if pos is not None:
                    latest_pos[:] = pos.flatten()
                if vel is not None:
                    latest_vel[:] = vel.flatten()

                # Apply pending command
                cmd = pending_cmd[0]
                if cmd is not None:
                    robot.set_joint_position_targets(cmd.reshape(1, -1))
                    pending_cmd[0] = None

    except KeyboardInterrupt:
        pass
    finally:
        running[0] = False
        t.join(timeout=2)
        robot_sock.close()
        cam_sock.close()
        ctx.term()
        sim_app.close()


if __name__ == "__main__":
    main()
