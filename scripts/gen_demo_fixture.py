"""Generate the demo episode fixture: meta.json + a placeholder cam_front.mp4.

Produces a synthetic 6-DOF + gripper sinusoidal trajectory at 30 Hz for 8 s
(240 frames). The video is a test pattern; replace with real-capture
footage when available.

Run from repo root:
    uv run python scripts/gen_demo_fixture.py
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "frontend" / "public" / "demo" / "episode_0"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FPS = 30
DURATION_SEC = 8.0
N_FRAMES = int(FPS * DURATION_SEC)
N_JOINTS = 6


def joint_at(frame_index: int, joint_index: int) -> float:
    t = frame_index / FPS
    amp = 0.6 - 0.08 * joint_index
    phase = joint_index * 0.7
    return amp * math.sin(0.6 * t + phase)


def gripper_at(frame_index: int) -> float:
    t = frame_index / FPS
    # Open then close then open cycle.
    return 0.5 + 0.5 * math.sin(0.4 * t)


frames = []
for i in range(N_FRAMES):
    frames.append({
        "t": round(i / FPS, 4),
        "joint_pos": [round(joint_at(i, j), 5) for j in range(N_JOINTS)],
        "joint_vel": [0.0] * N_JOINTS,
        "joint_effort": [0.0] * N_JOINTS,
        "gripper_pos": round(gripper_at(i), 4),
        "ee_pos": [
            round(0.3 + 0.1 * math.cos(0.6 * i / FPS), 4),
            round(0.0 + 0.1 * math.sin(0.6 * i / FPS), 4),
            round(0.2, 4),
        ],
        "ee_rotvec": [0.0, 0.0, 0.0],
    })

meta = {
    "episode_index": 0,
    "task": "Pick the red cube",
    "duration_sec": DURATION_SEC,
    "num_frames": N_FRAMES,
    "fps": FPS,
    "cameras": ["front"],
    "robot": "so101",
    "joint_names": [f"joint_{i}" for i in range(N_JOINTS)],
    "frames": frames,
}

meta_path = OUT_DIR / "meta.json"
meta_path.write_text(json.dumps(meta))
print(f"wrote {meta_path} ({meta_path.stat().st_size} bytes)")

mp4_path = OUT_DIR / "cam_front.mp4"
subprocess.run(
    [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=size=224x224:rate={FPS}:duration={DURATION_SEC}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "28", "-preset", "slow",
        "-movflags", "+faststart",
        str(mp4_path),
    ],
    check=True,
)
print(f"wrote {mp4_path} ({mp4_path.stat().st_size} bytes)")
