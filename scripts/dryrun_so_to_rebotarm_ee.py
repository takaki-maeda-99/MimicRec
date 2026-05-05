"""Dry-run the SO-101 → reBotArm EE-space teleop mapper.

Connects only to the SO-101 leader (no reBotArm daemon, no commands
sent to anything). Each tick reads the leader, runs it through
``SOToReBotArmEEMapper``, and prints what would be sent — including
the IK round-trip error so the operator can spot bad targets *before*
running the mapper for real on hardware.

Usage (from repo root):

    .venv/bin/python scripts/dryrun_so_to_rebotarm_ee.py

CLI options:
    --port              SO-101 leader port (default /dev/ttyACM1)
    --id                SO-101 leader id (default my_awesome_leader_arm)
    --mapper-config     mapper YAML (default configs/mapper/so_to_rebotarm_ee.yaml)
    --interval          seconds between ticks (default 0.5)
    --seed-deg          initial reBotArm joint seed for IK, comma-separated
                        degrees (default "0,0,0,0,0,0")
    --use-prev-as-seed  use previous IK output as next seed (closer to
                        the live session loop's behavior, where the IK
                        seed is the live joint_pos)
    --pos-warn-m        warn when IK position error exceeds this (m;
                        default 0.005)
    --ori-warn-rad      warn when IK orientation error exceeds this
                        (rad; default 0.15 ≈ 8.6°)

Refuses to run if the MimicRec backend has an active session — the
session would be holding /dev/ttyACM1.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from pathlib import Path

import numpy as np
from omegaconf import OmegaConf


REPO_ROOT = Path(__file__).resolve().parents[1]


def _check_no_active_session() -> None:
    """Refuse to run if the MimicRec backend is holding the SO-101 port."""
    import urllib.request
    try:
        with urllib.request.urlopen(
            "http://localhost:8000/api/session/state", timeout=0.5
        ) as r:
            data = json.loads(r.read())
        if data.get("state") and data["state"] != "idle":
            print(
                f"ERROR: MimicRec backend has an ACTIVE session "
                f"(state={data['state']!r}). End it first:\n"
                f"  curl -X POST http://localhost:8000/api/session/end\n",
                file=sys.stderr,
            )
            sys.exit(3)
    except Exception:
        # Backend not running / unreachable — fine for diagnostics
        pass


def _resolve_mapper_kwargs(cfg_path: Path) -> dict:
    """Load the mapper YAML and resolve relative URDF / package paths.

    Mirrors ``backend/mimicrec/api/deps.py`` so the dry-run sees the
    exact same kwargs the real session would pass to the mapper.
    """
    cfg = OmegaConf.load(cfg_path)
    kwargs = {k: v for k, v in OmegaConf.to_container(cfg).items()
              if k not in ("_target_",)}
    for key in ("so101_urdf_path", "rebotarm_urdf_path"):
        v = kwargs.get(key)
        if isinstance(v, str) and not Path(v).is_absolute():
            kwargs[key] = str((REPO_ROOT / v).resolve())
    pkg_dirs = kwargs.get("rebotarm_package_dirs")
    if isinstance(pkg_dirs, list):
        kwargs["rebotarm_package_dirs"] = [
            str((REPO_ROOT / d).resolve())
            if isinstance(d, str) and not Path(d).is_absolute() else d
            for d in pkg_dirs
        ]
    return kwargs


def _angular_error_rad(R_a: np.ndarray, R_b: np.ndarray) -> float:
    """Geodesic angle between two rotation matrices, in radians."""
    R_rel = R_a.T @ R_b
    cos_theta = (np.trace(R_rel) - 1.0) * 0.5
    cos_theta = float(np.clip(cos_theta, -1.0, 1.0))
    return float(np.arccos(cos_theta))


def _fmt_deg(arr: np.ndarray) -> str:
    return "[" + ", ".join(f"{float(v):+7.2f}" for v in arr) + "]"


def _fmt_pos(arr: np.ndarray) -> str:
    return "[" + ", ".join(f"{float(v):+.4f}" for v in arr) + "]"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="/dev/ttyACM1")
    parser.add_argument("--id", default="my_awesome_leader_arm")
    parser.add_argument(
        "--mapper-config",
        default="configs/mapper/so_to_rebotarm_ee.yaml",
        help="path to mapper YAML (relative to repo root)",
    )
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument(
        "--seed-deg",
        default="0,0,0,0,0,0",
        help="initial reBotArm seed (deg), comma-separated",
    )
    parser.add_argument("--use-prev-as-seed", action="store_true")
    parser.add_argument("--pos-warn-m", type=float, default=0.005)
    parser.add_argument("--ori-warn-rad", type=float, default=0.15)
    # Mapper override flags for dryrun-only experimentation. These
    # override values from the YAML so you don't have to keep editing
    # it while diagnosing IK / step-cap issues.
    parser.add_argument(
        "--max-ee-step-m", type=float, default=None,
        help="override mapper max_ee_step_m. Set high (e.g. 10.0) "
             "to disable the step cap that otherwise hides fresh IK "
             "outputs behind the cached last command.",
    )
    parser.add_argument(
        "--ik-orientation-weight", type=float, default=None,
        help="override mapper ik_orientation_weight. 0 = pure "
             "position IK (drops orientation entirely).",
    )
    parser.add_argument(
        "--ik-position-weight", type=float, default=None,
        help="override mapper ik_position_weight",
    )
    parser.add_argument(
        "--workspace-radius-m", type=float, default=None,
        help="override mapper workspace_radius_m. 0 = disable.",
    )
    parser.add_argument(
        "--max-joint-step-deg", type=float, default=None,
        help="override mapper max_joint_step_deg. 0 = disable the "
             "joint-space velocity guard.",
    )
    args = parser.parse_args()

    _check_no_active_session()

    cfg_path = (REPO_ROOT / args.mapper_config).resolve()
    if not cfg_path.is_file():
        print(f"ERROR: mapper config not found: {cfg_path}", file=sys.stderr)
        return 2
    kwargs = _resolve_mapper_kwargs(cfg_path)
    overrides_applied: list[str] = []
    if args.max_ee_step_m is not None:
        kwargs["max_ee_step_m"] = args.max_ee_step_m
        overrides_applied.append(f"max_ee_step_m={args.max_ee_step_m}")
    if args.ik_orientation_weight is not None:
        kwargs["ik_orientation_weight"] = args.ik_orientation_weight
        overrides_applied.append(f"ik_orientation_weight={args.ik_orientation_weight}")
    if args.ik_position_weight is not None:
        kwargs["ik_position_weight"] = args.ik_position_weight
        overrides_applied.append(f"ik_position_weight={args.ik_position_weight}")
    if args.workspace_radius_m is not None:
        kwargs["workspace_radius_m"] = args.workspace_radius_m
        overrides_applied.append(f"workspace_radius_m={args.workspace_radius_m}")
    if args.max_joint_step_deg is not None:
        kwargs["max_joint_step_deg"] = args.max_joint_step_deg
        overrides_applied.append(f"max_joint_step_deg={args.max_joint_step_deg}")

    # Defer heavy imports until after CLI parsing so --help is fast.
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from mimicrec.adapters.so_leader import SOLeaderAdapter
    from mimicrec.mappers.so_to_rebotarm_ee import SOToReBotArmEEMapper
    from mimicrec.types import RobotState
    from lerobot.model.kinematics import RobotKinematics

    print(f"Loading mapper from {cfg_path} ...")
    mapper = SOToReBotArmEEMapper(**kwargs)
    # Separate FK instance to verify the IK round-trip without
    # disturbing the mapper's internal placo solver state.
    rebotarm_fk = RobotKinematics(
        urdf_path=kwargs["rebotarm_urdf_path"],
        target_frame_name=kwargs.get("rebotarm_ee_frame", "end_link"),
        joint_names=list(kwargs["rebotarm_arm_joints"]),
    )

    seed_deg = np.asarray(
        [float(x) for x in args.seed_deg.split(",")], dtype=np.float64
    )
    dof = len(kwargs["rebotarm_arm_joints"])
    if seed_deg.shape[0] != dof:
        print(
            f"ERROR: --seed-deg has {seed_deg.shape[0]} elems, expected {dof}",
            file=sys.stderr,
        )
        return 2
    seed_rad = np.deg2rad(seed_deg).astype(np.float32)

    print(f"Connecting SO-101 leader on {args.port} (id={args.id}) ...")
    leader = SOLeaderAdapter(port=args.port, id=args.id)
    try:
        await leader.connect()
    except Exception as e:
        print(f"ERROR: leader connect failed: {type(e).__name__}: {e}",
              file=sys.stderr)
        return 1

    stop = asyncio.Event()

    def _sigint(_sig, _frame):
        stop.set()

    signal.signal(signal.SIGINT, _sigint)
    signal.signal(signal.SIGTERM, _sigint)

    print(
        f"Dry-run started. interval={args.interval}s. Ctrl+C to stop.\n"
        f"  IK warn thresholds: pos>{args.pos_warn_m}m  ori>{args.ori_warn_rad}rad\n"
        f"  seed strategy: {'prev IK out' if args.use_prev_as_seed else 'fixed --seed-deg'}\n"
        + (f"  overrides: {' '.join(overrides_applied)}\n" if overrides_applied else "")
    )

    tick = 0
    current_seed_rad = seed_rad.copy()
    try:
        while not stop.is_set():
            tick += 1
            try:
                action = await leader.read_action()
            except Exception as e:
                print(f"[tick {tick}] leader read error: {type(e).__name__}: {e}",
                      file=sys.stderr)
                await asyncio.sleep(args.interval)
                continue

            so = action.target_joint_pos
            if so is None:
                print(f"[tick {tick}] leader returned None")
                await asyncio.sleep(args.interval)
                continue

            # Build a synthetic RobotState whose joint_pos is the seed.
            state = RobotState(
                joint_pos=current_seed_rad.copy(),
                joint_vel=np.zeros(dof, dtype=np.float32),
                joint_effort=np.zeros(dof, dtype=np.float32),
            )

            so_arr = np.asarray(so, dtype=np.float64)
            n_arm = len(kwargs["so101_arm_joints"])
            T_so = mapper._so101_fk.forward_kinematics(so_arr[:n_arm])
            pos_in = np.asarray(T_so[:3, 3], dtype=np.float64)

            # Snapshot mapper state before map() to surface the
            # leader-Δ that drove this tick.
            prev_so_pos = (
                mapper._prev_so_pos.copy()
                if mapper._prev_so_pos is not None else None
            )
            prev_target_pos = (
                mapper._target_pos.copy()
                if mapper._target_pos is not None else None
            )

            cmd = mapper.map(action, state)

            target_pos = mapper._target_pos
            target_R = mapper._target_R
            so_dp = (pos_in - prev_so_pos) if prev_so_pos is not None else None

            q_rad = np.asarray(cmd.q, dtype=np.float64)
            q_deg = np.rad2deg(q_rad)
            T_actual = rebotarm_fk.forward_kinematics(q_deg)
            actual_pos = np.asarray(T_actual[:3, 3], dtype=np.float64)
            actual_R = np.asarray(T_actual[:3, :3], dtype=np.float64)

            pos_err = (
                float(np.linalg.norm(actual_pos - target_pos))
                if target_pos is not None else float("nan")
            )
            ori_err = (
                _angular_error_rad(target_R, actual_R)
                if target_R is not None else float("nan")
            )

            pos_warn = "  ⚠ POS" if pos_err > args.pos_warn_m else ""
            ori_warn = "  ⚠ ORI" if ori_err > args.ori_warn_rad else ""

            # Detect whether the target advanced this tick (delta
            # accepted) vs was held (workspace / discontinuity guard).
            if prev_target_pos is None:
                target_status = "[INIT]"
            elif np.allclose(prev_target_pos, target_pos, atol=1e-9):
                target_status = "[HELD]"
            else:
                target_status = "[fresh]"

            print(
                f"[tick {tick:4d}] {target_status}\n"
                f"  SO101 deg: {_fmt_deg(so_arr[:n_arm])}  grip={float(so_arr[n_arm]):+.1f}\n"
                f"  SO101 EE pos: {_fmt_pos(pos_in)}"
                + (f"  Δp={_fmt_pos(so_dp)} (|Δp|={float(np.linalg.norm(so_dp)):.4f}m)\n"
                   if so_dp is not None else "\n")
                + f"  target pos:   {_fmt_pos(target_pos) if target_pos is not None else 'N/A'}\n"
                f"  IK seed deg:  {_fmt_deg(np.rad2deg(current_seed_rad))}\n"
                f"  IK out  deg:  {_fmt_deg(q_deg)}\n"
                f"  achieved pos: {_fmt_pos(actual_pos)}\n"
                f"  IK pos err: {pos_err:.4f}m{pos_warn}   ori err: {ori_err:.3f}rad ({np.rad2deg(ori_err):.1f}°){ori_warn}\n"
                f"  gripper out: {cmd.gripper}\n"
            )

            if args.use_prev_as_seed:
                current_seed_rad = q_rad.astype(np.float32)

            await asyncio.sleep(args.interval)
    finally:
        await leader.disconnect()
        print("Dry-run stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
