#!/usr/bin/env python
"""Isaac Sim bridge server for MimicRec.

    ~/isaacsim/python.sh scripts/sim_bridge_isaacsim.py
    ~/isaacsim/python.sh scripts/sim_bridge_isaacsim.py --robot franka --headless
    ~/isaacsim/python.sh scripts/sim_bridge_isaacsim.py --robot franka --headless --camera
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
    parser.add_argument("--camera", action="store_true", help="Enable camera rendering and streaming")
    parser.add_argument("--camera_width", type=int, default=640)
    parser.add_argument("--camera_height", type=int, default=480)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    from isaacsim import SimulationApp
    # render=True even in headless to enable camera capture
    sim_app = SimulationApp({"headless": args.headless, "width": args.camera_width, "height": args.camera_height})

    from isaacsim.core.api import World
    from isaacsim.storage.native import get_assets_root_path
    import isaacsim.core.utils.stage as stage_utils
    from isaacsim.core.prims import SingleArticulation
    from pxr import UsdGeom, Gf
    import omni.usd
    import sys

    world = World(stage_units_in_meters=1.0)
    world.scene.add_default_ground_plane()
    assets = get_assets_root_path()

    if args.robot == "franka":
        usd = assets + "/Isaac/Robots/FrankaRobotics/FrankaPanda/franka.usd"
        prim_path = args.robot_prim or "/World/Franka"
        stage_utils.add_reference_to_stage(usd, prim_path)
    elif args.robot.startswith("usd:"):
        omni.usd.get_context().open_stage(args.robot[4:])
        prim_path = args.robot_prim or "/World/Robot"
    else:
        print(f"Unknown robot: {args.robot}")
        return

    # Create camera if requested
    camera_annotator = None
    if args.camera:
        stage = omni.usd.get_context().get_stage()
        # Create a camera prim looking at the robot
        cam_prim = UsdGeom.Camera.Define(stage, "/World/MimicRecCam")
        cam_prim.GetFocalLengthAttr().Set(24.0)
        xform = UsdGeom.Xformable(cam_prim.GetPrim())
        xform.ClearXformOpOrder()
        xform.AddTranslateOp().Set(Gf.Vec3d(1.5, 1.5, 1.2))
        # Point camera toward robot origin
        xform.AddRotateXYZOp().Set(Gf.Vec3f(-30, 0, 135))
        sys.stderr.write(f"Camera created at /World/MimicRecCam\n")

    world.reset()
    robot = SingleArticulation(prim_path=prim_path, name="robot")
    robot.initialize()
    dof = robot.num_dof
    joint_names = list(robot.dof_names)

    # Set up replicator camera capture after world.reset()
    if args.camera:
        try:
            import omni.replicator.core as rep
            rp = rep.create.render_product("/World/MimicRecCam", (args.camera_width, args.camera_height))
            camera_annotator = rep.AnnotatorRegistry.get_annotator("rgb")
            camera_annotator.attach([rp])
            sys.stderr.write(f"Camera annotator attached ({args.camera_width}x{args.camera_height})\n")
        except Exception as e:
            sys.stderr.write(f"Camera setup failed: {e}\n")
            camera_annotator = None

    import zmq
    ctx = zmq.Context()

    robot_sock = ctx.socket(zmq.ROUTER)
    robot_sock.bind(f"tcp://*:{args.robot_port}")

    cam_sock = ctx.socket(zmq.PUB)
    cam_sock.bind(f"tcp://*:{args.camera_port}")

    open("/tmp/mimicrec_bridge_ready", "w").write("1")
    sys.stderr.write(f"BRIDGE READY: DOF={dof}, joints={joint_names}, camera={'ON' if camera_annotator else 'OFF'}\n")

    pending_cmd = None
    frame_count = 0

    try:
        while sim_app.is_running():
            # 1. Handle ZMQ messages
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

            # 3. Step simulation (always render to enable camera capture)
            world.step(render=True)

            # 4. Publish camera frame at ~15 Hz (every 4th step at 60 Hz)
            if camera_annotator and frame_count % 4 == 0:
                try:
                    data = camera_annotator.get_data()
                    if data is not None and len(data) > 0:
                        import cv2
                        rgb = np.array(data)
                        if rgb.ndim == 3 and rgb.shape[2] >= 3:
                            bgr = cv2.cvtColor(rgb[:, :, :3], cv2.COLOR_RGB2BGR)
                            _, jpeg = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])
                            cam_sock.send_multipart([b"sim_front", jpeg.tobytes()])
                except Exception as ex:
                    if frame_count % 240 == 0:  # Log every ~4 seconds
                        sys.stderr.write(f"CAM: {ex}\n")

            frame_count += 1
            time.sleep(1.0 / 60.0)

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
