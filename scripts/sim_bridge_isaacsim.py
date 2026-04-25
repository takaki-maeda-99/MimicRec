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

    robot_sock = ctx.socket(zmq.ROUTER)
    robot_sock.bind(f"tcp://*:{args.robot_port}")

    cam_sock = ctx.socket(zmq.PUB)
    cam_sock.bind(f"tcp://*:{args.camera_port}")

    # Write ready signal
    open("/tmp/mimicrec_bridge_ready", "w").write("1")
    import sys
    sys.stderr.write(f"BRIDGE READY: DOF={dof}, joints={joint_names}\n")

    pending_cmd = None

    try:
        while sim_app.is_running():
            # 1. Handle ALL pending ZMQ messages (drain the queue)
            #    ROUTER receives [identity, empty, data] and must reply [identity, empty, data]
            for _ in range(100):
                try:
                    frames = robot_sock.recv_multipart(zmq.NOBLOCK)
                except zmq.Again:
                    break

                identity = frames[0]
                import json as _json
                msg = _json.loads(frames[-1])

                def reply(data):
                    robot_sock.send_multipart([identity, b"", _json.dumps(data).encode()])

                cmd = msg.get("cmd")
                if cmd == "connect":
                    reply({"ok": True, "dof": dof, "joint_names": joint_names})
                elif cmd == "read_state":
                    pos = robot.get_joint_positions()
                    vel = robot.get_joint_velocities()
                    reply({
                        "joint_pos": pos.flatten().tolist() if pos is not None else [0] * dof,
                        "joint_vel": vel.flatten().tolist() if vel is not None else [0] * dof,
                        "joint_effort": [0.0] * dof,
                    })
                elif cmd == "send_command":
                    pending_cmd = np.array(msg["q"], dtype=np.float32)
                    reply({"ok": True})
                elif cmd == "set_mode":
                    reply({"ok": True})
                elif cmd == "disconnect":
                    reply({"ok": True})
                elif cmd == "shutdown":
                    reply({"ok": True})
                    raise KeyboardInterrupt
                else:
                    reply({"ok": True})

            # 2. Apply pending command
            if pending_cmd is not None:
                try:
                    from isaacsim.core.utils.types import ArticulationAction
                    robot.apply_action(ArticulationAction(joint_positions=pending_cmd))
                except Exception as ex:
                    sys.stderr.write(f"CMD ERROR: {ex}\n")
                pending_cmd = None

            # 3. Step simulation at ~60 Hz (not max speed)
            world.step(render=not args.headless)
            time.sleep(1.0 / 60.0)  # cap sim rate, ensures ZMQ gets polled regularly

    except KeyboardInterrupt:
        sys.stderr.write("Interrupted\n")
    except Exception as e:
        sys.stderr.write(f"LOOP CRASHED: {type(e).__name__}: {e}\n")
        import traceback
        traceback.print_exc(file=sys.stderr)
    finally:
        sys.stderr.write("Shutting down...\n")
        robot_sock.close()
        cam_sock.close()
        ctx.term()
        sim_app.close()


if __name__ == "__main__":
    main()
