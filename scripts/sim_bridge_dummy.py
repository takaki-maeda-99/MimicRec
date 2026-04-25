#!/usr/bin/env python
"""Dummy sim bridge for testing without a real simulator.

Responds to MimicRec's ZMQ protocol with fake joint data.
Useful for verifying the adapter works before setting up Isaac Sim.

    python scripts/sim_bridge_dummy.py
"""
import json
import math
import time

import numpy as np
import zmq


def main():
    ctx = zmq.Context()

    # Robot REP socket
    robot_sock = ctx.socket(zmq.REP)
    robot_sock.bind("tcp://*:5556")
    robot_sock.setsockopt(zmq.RCVTIMEO, 100)

    # Camera PUB socket
    cam_sock = ctx.socket(zmq.PUB)
    cam_sock.bind("tcp://*:5557")

    dof = 6
    joint_names = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
    q = np.zeros(dof, dtype=np.float32)
    t0 = time.time()

    print(f"Dummy sim bridge running (robot: 5556, camera: 5557)")
    print("Ctrl+C to stop")

    try:
        while True:
            # Simulate gentle oscillation
            t = time.time() - t0
            for i in range(dof):
                q[i] = 10.0 * math.sin(t * 0.5 + i * 0.5)

            # Handle robot commands
            try:
                msg = robot_sock.recv_json(zmq.NOBLOCK)
                cmd = msg.get("cmd")

                if cmd == "connect":
                    robot_sock.send_json({"ok": True, "dof": dof, "joint_names": joint_names})
                    print("Client connected")
                elif cmd == "read_state":
                    robot_sock.send_json({
                        "joint_pos": q.tolist(),
                        "joint_vel": [0.0] * dof,
                        "joint_effort": [0.0] * dof,
                    })
                elif cmd == "send_command":
                    q = np.array(msg["q"], dtype=np.float32)
                    robot_sock.send_json({"ok": True})
                elif cmd == "set_mode":
                    robot_sock.send_json({"ok": True})
                elif cmd == "disconnect":
                    robot_sock.send_json({"ok": True})
                    print("Client disconnected")
                else:
                    robot_sock.send_json({"error": f"unknown: {cmd}"})
            except zmq.Again:
                pass

            # Publish a fake camera frame (solid color)
            import cv2
            img = np.full((240, 320, 3), int(128 + 64 * math.sin(t)), dtype=np.uint8)
            cv2.putText(img, f"SIM t={t:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            _, jpeg = cv2.imencode(".jpg", img)
            cam_sock.send_multipart([b"sim_front", jpeg.tobytes()])

            time.sleep(0.033)  # ~30 Hz

    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        robot_sock.close()
        cam_sock.close()
        ctx.term()


if __name__ == "__main__":
    main()
