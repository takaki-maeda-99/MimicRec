"""Move the arm smoothly to a configured idle pose.

The idle pose lives in ``configs/rebotarm/idle_pose.yaml`` (captured via
the daemon's ``read_state``). This module loads it and exposes
``move_to_idle()`` — an async helper that reads the current pose,
linearly ramps joint + gripper setpoints to the idle pose at a fixed
rate, and leaves the arm in a caller-chosen mode (POSITION to hold,
GRAVITY_COMP for hand-teaching).
"""
from __future__ import annotations

import logging
import math
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from mimicrec.adapters.robot import RobotAdapter, RobotMode
from mimicrec.util.clock import Clock, RealClock

logger = logging.getLogger(__name__)


# Anchor to the repo root via __file__ so the lookup survives whatever
# cwd uvicorn / the test runner / scripts happen to be launched from.
# backend/mimicrec/session/idle.py → parents[3] is the repo root.
DEFAULT_IDLE_POSE_PATH = (
    Path(__file__).resolve().parents[3] / "configs/rebotarm/idle_pose.yaml"
)


@dataclass(frozen=True)
class IdlePose:
    joint_pos_rad: np.ndarray  # shape (dof,), float32
    gripper_pos: float | None
    joint_names: tuple[str, ...]


def load_idle_pose(path: Path | str = DEFAULT_IDLE_POSE_PATH) -> IdlePose:
    p = Path(path)
    doc = yaml.safe_load(p.read_text())
    return IdlePose(
        joint_pos_rad=np.asarray(doc["joint_pos_rad"], dtype=np.float32),
        gripper_pos=(
            float(doc["gripper_pos"])
            if doc.get("gripper_pos") is not None
            else None
        ),
        joint_names=tuple(doc.get("joint_names", [])),
    )


def save_idle_pose(
    pose: IdlePose,
    path: Path | str = DEFAULT_IDLE_POSE_PATH,
    *,
    source: str = "ui_capture",
) -> dict:
    """Serialize ``pose`` to YAML at ``path`` (atomic via temp+rename).

    Returns the dict that was written so callers can include it in API
    responses without re-reading the file.
    """
    p = Path(path)
    rad_list = [float(x) for x in pose.joint_pos_rad.tolist()]
    doc = {
        "joint_names": list(pose.joint_names),
        "joint_pos_rad": rad_list,
        "joint_pos_deg": [math.degrees(x) for x in rad_list],
        "gripper_pos": (None if pose.gripper_pos is None else float(pose.gripper_pos)),
        "captured_at_unix": time.time(),
        "source": source,
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=p.parent)
    try:
        with os.fdopen(fd, "w") as f:
            yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)
        os.replace(tmp_path, p)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise
    return doc


async def move_to_idle(
    adapter: RobotAdapter,
    *,
    idle_pose: IdlePose | None = None,
    duration_sec: float = 3.0,
    fps: int = 30,
    hold_sec: float = 1.0,
    after_mode: RobotMode = RobotMode.POSITION,
    clock: Clock | None = None,
) -> None:
    """Linearly ramp the arm (and gripper, if both ends are known) from the
    current measured pose to the configured idle pose, then hold POSITION
    for ``hold_sec`` before releasing into ``after_mode``.

    Switches the daemon to POSITION before issuing setpoints — the daemon
    seeds its position controller with the live measured pose on mode
    entry, so the first step is a no-op delta and there is no snap.

    The post-ramp hold lets residual momentum from the ramp die out
    against the rigid POSITION controller. Without it, when the hold
    releases into GRAVITY_COMP, the arm carries forward and tilts past
    idle. Set ``hold_sec=0`` to disable.
    """
    if idle_pose is None:
        idle_pose = load_idle_pose()
    if clock is None:
        clock = RealClock()
    if duration_sec <= 0:
        raise ValueError(f"duration_sec must be > 0, got {duration_sec}")
    if fps <= 0:
        raise ValueError(f"fps must be > 0, got {fps}")
    if hold_sec < 0:
        raise ValueError(f"hold_sec must be >= 0, got {hold_sec}")

    start = await adapter.read_state()
    q_start = np.asarray(start.joint_pos, dtype=np.float32)
    q_goal = idle_pose.joint_pos_rad.astype(np.float32)
    if q_start.shape != q_goal.shape:
        raise ValueError(
            f"idle pose dof {q_goal.shape} != adapter dof {q_start.shape}"
        )

    has_gripper_api = hasattr(adapter, "send_gripper_command")
    g_goal = idle_pose.gripper_pos
    g_start = start.gripper_pos
    do_gripper = has_gripper_api and g_goal is not None
    # If we have a goal but no live reading, hold the goal throughout.
    if do_gripper and g_start is None:
        g_start = g_goal

    await adapter.set_mode(RobotMode.POSITION)

    n_steps = max(1, int(round(duration_sec * fps)))
    tick_interval_ns = 1_000_000_000 // fps
    next_tick_ns = clock.monotonic_ns() + tick_interval_ns

    n_hold = int(round(hold_sec * fps))
    logger.info(
        "[idle] start: q_start=%s q_goal=%s gripper=%s steps=%d hold=%d (~%.2fs ramp + %.2fs hold @ %dHz) after=%s",
        q_start.tolist(), q_goal.tolist(),
        f"{g_start}->{g_goal}" if do_gripper else "skip",
        n_steps, n_hold, duration_sec, hold_sec, fps, after_mode.value,
    )

    for i in range(1, n_steps + 1):
        alpha = i / n_steps
        q_cmd = (q_start + (q_goal - q_start) * alpha).astype(np.float32)
        await adapter.send_joint_command(q_cmd)
        if do_gripper:
            g_cmd = float(g_start + (g_goal - g_start) * alpha)
            await adapter.send_gripper_command(g_cmd)
        await clock.sleep_until(next_tick_ns)
        next_tick_ns += tick_interval_ns

    # Hold idle under POSITION so residual ramp momentum bleeds off
    # against the rigid controller before releasing to after_mode.
    for _ in range(n_hold):
        await adapter.send_joint_command(q_goal)
        if do_gripper:
            await adapter.send_gripper_command(float(g_goal))
        await clock.sleep_until(next_tick_ns)
        next_tick_ns += tick_interval_ns

    if after_mode != RobotMode.POSITION:
        await adapter.set_mode(after_mode)

    logger.info("[idle] done; mode=%s", after_mode.value)
