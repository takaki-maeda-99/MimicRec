#!/usr/bin/env python
"""Isaac Sim bridge server for MimicRec.

Run inside Isaac Sim's Python:
    ~/isaacsim/python.sh scripts/sim_bridge_isaacsim.py

This spawns a Franka robot (or any specified robot) in Isaac Sim and
bridges it to MimicRec via ZMQ.

Options:
    --robot franka          Use built-in Franka Panda (default)
    --robot usd:/path.usd   Load a custom USD scene
    --headless              Run without GUI
    --robot_port 5556       ZMQ REP port for robot commands
    --camera_port 5557      ZMQ PUB port for camera frames
"""
from __future__ import annotations

import argparse
import time

import numpy as np


def main():
    parser = argparse.ArgumentParser(description="Isaac Sim bridge for MimicRec")
    parser.add_argument("--robot", default="franka", help="'franka' or 'usd:/path/to/scene.usd'")
    parser.add_argument("--robot_prim", default=None, help="Articulation prim path (auto-detected if omitted)")
    parser.add_argument("--robot_port", type=int, default=5556)
    parser.add_argument("--camera_port", type=int, default=5557)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    # --- Isaac Sim startup ---
    from isaacsim import SimulationApp
    sim_app = SimulationApp({"headless": args.headless})

    from isaacsim.core.api import World
    from isaacsim.core.prims import SingleArticulation
    import isaacsim.core.utils.stage as stage_utils
    from isaacsim.storage.native import get_assets_root_path

    world = World(stage_units_in_meters=1.0)
    world.scene.add_default_ground_plane()

    # --- Spawn robot ---
    if args.robot == "franka":
        asset_path = get_assets_root_path() + "/Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd"
        prim_path = args.robot_prim or "/World/Franka"
        stage_utils.add_reference_to_stage(asset_path, prim_path)
        robot = SingleArticulation(prim_path=prim_path, name="robot")
    elif args.robot.startswith("usd:"):
        usd_path = args.robot[4:]
        import omni.usd
        omni.usd.get_context().open_stage(usd_path)
        prim_path = args.robot_prim or "/World/Robot"
        robot = SingleArticulation(prim_path=prim_path, name="robot")
    else:
        print(f"Unknown robot: {args.robot}")
        return

    world.reset()
    robot.initialize()

    dof = robot.num_dof
    joint_names = [f"joint_{i}" for i in range(dof)]
    try:
        joint_names = list(robot.dof_names)
    except Exception:
        pass

    print(f"Robot: {prim_path}, DOF: {dof}, Joints: {joint_names}")

    # --- ZMQ ---
    import zmq
    ctx = zmq.Context()

    robot_sock = ctx.socket(zmq.REP)
    robot_sock.bind(f"tcp://*:{args.robot_port}")
    robot_sock.setsockopt(zmq.RCVTIMEO, 50)

    cam_sock = ctx.socket(zmq.PUB)
    cam_sock.bind(f"tcp://*:{args.camera_port}")

    print(f"Bridge: robot={args.robot_port}, camera={args.camera_port}")
    print("Ready. Ctrl+C to stop.")

    frame_count = 0
    try:
        while sim_app.is_running():
            world.step(render=not args.headless)

            try:
                msg = robot_sock.recv_json(zmq.NOBLOCK)
                cmd = msg.get("cmd")

                if cmd == "connect":
                    robot_sock.send_json({"ok": True, "dof": dof, "joint_names": joint_names})
                elif cmd == "read_state":
                    pos = robot.get_joint_positions()
                    vel = robot.get_joint_velocities()
                    robot_sock.send_json({
                        "joint_pos": pos.flatten().tolist() if pos is not None else [0.0] * dof,
                        "joint_vel": vel.flatten().tolist() if vel is not None else [0.0] * dof,
                        "joint_effort": [0.0] * dof,
                    })
                elif cmd == "send_command":
                    q = np.array(msg["q"], dtype=np.float32)
                    robot.set_joint_position_targets(q.reshape(1, -1))
                    robot_sock.send_json({"ok": True})
                elif cmd == "set_mode":
                    robot_sock.send_json({"ok": True})
                elif cmd == "disconnect":
                    robot_sock.send_json({"ok": True})
                else:
                    robot_sock.send_json({"error": f"unknown: {cmd}"})
            except zmq.Again:
                pass

            # Camera: publish viewport render at ~15 Hz
            if frame_count % 4 == 0:
                try:
                    from isaacsim.core.utils.viewports import get_viewport_data
                    rgba = get_viewport_data()
                    if rgba is not None:
                        import cv2
                        bgr = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2BGR)
                        _, jpeg = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])
                        cam_sock.send_multipart([b"sim_front", jpeg.tobytes()])
                except Exception:
                    pass

            frame_count += 1

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        robot_sock.close()
        cam_sock.close()
        ctx.term()
        sim_app.close()


if __name__ == "__main__":
    main()
