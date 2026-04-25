#!/usr/bin/env python
"""Isaac Sim bridge server for MimicRec.

Run this script *inside* Isaac Sim's Python environment:

    ~/isaacsim/python.sh scripts/sim_bridge_isaacsim.py --usd_path /path/to/scene.usd

It starts a ZMQ REP server on port 5556 (robot) and a ZMQ PUB server
on port 5557 (cameras), bridging MimicRec's adapter protocol to Isaac Sim's
Articulation API.

Requirements:
    - Isaac Sim 5.0+ with a scene containing an ArticulationRootAPI prim
    - zmq (pip install pyzmq inside Isaac Sim's python)
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np


def main():
    parser = argparse.ArgumentParser(description="Isaac Sim bridge for MimicRec")
    parser.add_argument("--usd_path", required=True, help="Path to USD scene with robot")
    parser.add_argument("--robot_prim", default="/World/Robot", help="Prim path to the robot articulation root")
    parser.add_argument("--robot_port", type=int, default=5556, help="ZMQ REP port for robot commands")
    parser.add_argument("--camera_port", type=int, default=5557, help="ZMQ PUB port for camera frames")
    parser.add_argument("--camera_prims", nargs="*", default=[], help="Prim paths for cameras (e.g. /World/Camera_front)")
    parser.add_argument("--headless", action="store_true", help="Run headless (no GUI)")
    args = parser.parse_args()

    # --- Isaac Sim setup ---
    from isaacsim import SimulationApp
    sim_app = SimulationApp({"headless": args.headless})

    import omni.usd
    from isaacsim.core.api import World
    from isaacsim.core.prims import Articulation

    # Load scene
    omni.usd.get_context().open_stage(args.usd_path)
    world = World(stage_units_in_meters=1.0)
    world.scene.add_default_ground_plane()

    # Get robot articulation
    robot = Articulation(prim_paths_expr=args.robot_prim)
    world.reset()
    robot.initialize()

    dof = robot.num_dof
    joint_names = [f"joint_{i}" for i in range(dof)]  # Override with actual names if available
    try:
        joint_names = list(robot.dof_names)
    except Exception:
        pass

    print(f"Robot: {args.robot_prim}, DOF: {dof}, Joints: {joint_names}")

    # --- ZMQ setup ---
    import zmq
    ctx = zmq.Context()

    # Robot command socket (REQ/REP)
    robot_sock = ctx.socket(zmq.REP)
    robot_sock.bind(f"tcp://*:{args.robot_port}")
    robot_sock.setsockopt(zmq.RCVTIMEO, 100)  # 100ms timeout for non-blocking polling
    print(f"Robot bridge listening on port {args.robot_port}")

    # Camera socket (PUB)
    cam_sock = ctx.socket(zmq.PUB)
    cam_sock.bind(f"tcp://*:{args.camera_port}")
    print(f"Camera bridge publishing on port {args.camera_port}")

    # Camera setup
    cameras = {}
    if args.camera_prims:
        import omni.replicator.core as rep
        for cam_prim in args.camera_prims:
            cam_name = cam_prim.split("/")[-1].lower()
            try:
                rp = rep.create.render_product(cam_prim, (640, 480))
                cameras[cam_name] = rp
                print(f"Camera: {cam_name} ({cam_prim})")
            except Exception as e:
                print(f"Warning: could not create camera for {cam_prim}: {e}")

    # --- Main loop ---
    print("Bridge running. Ctrl+C to stop.")
    frame_count = 0
    try:
        while sim_app.is_running():
            world.step(render=not args.headless)

            # Handle robot commands (non-blocking)
            try:
                msg = robot_sock.recv_json(zmq.NOBLOCK)
                cmd = msg.get("cmd")

                if cmd == "connect":
                    robot_sock.send_json({
                        "ok": True,
                        "dof": dof,
                        "joint_names": joint_names,
                    })

                elif cmd == "read_state":
                    pos = robot.get_joint_positions().flatten().tolist()
                    vel = robot.get_joint_velocities().flatten().tolist()
                    effort = [0.0] * dof  # Isaac Sim doesn't always expose effort
                    try:
                        eff = robot.get_applied_joint_efforts()
                        if eff is not None:
                            effort = eff.flatten().tolist()
                    except Exception:
                        pass
                    robot_sock.send_json({
                        "joint_pos": pos,
                        "joint_vel": vel,
                        "joint_effort": effort,
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
                    robot_sock.send_json({"error": f"unknown command: {cmd}"})

            except zmq.Again:
                pass  # No message waiting

            # Publish camera frames at ~15 Hz
            if frame_count % 4 == 0 and cameras:
                import cv2
                for cam_name, rp in cameras.items():
                    try:
                        frame = rep.AnnotatorRegistry.get_annotator("rgb").attach(rp)
                        rgb = frame.get_data()
                        if rgb is not None:
                            bgr = cv2.cvtColor(rgb[:, :, :3], cv2.COLOR_RGB2BGR)
                            _, jpeg = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])
                            cam_sock.send_multipart([
                                cam_name.encode(),
                                jpeg.tobytes(),
                            ])
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
