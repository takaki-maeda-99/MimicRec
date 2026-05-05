"""Episode-table conversion to VLA-compat schema (pure)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyarrow as pa
from scipy.spatial.transform import Rotation as R

from mimicrec.adapters.types import GripperConvention, ProprioLayout


@dataclass(frozen=True)
class ConvertedEpisode:
    table: pa.Table


_PASSTHROUGH_COLUMNS = (
    "timestamp",
    "frame_index",
    "episode_index",
    "index",
    "task_index",
)

_REQUIRED_INPUT_COLUMNS = (
    "observation.state.ee_pos",
    "observation.state.ee_rotvec",
)

# Real per-step rotation deltas at 15-30 fps stay well below this. Hitting
# it indicates frame mismatch or bad input data — fail loudly rather than
# emit an axis-discontinuity sample.
_ROT_DELTA_SANITY_RAD = 1.0


def _to_T(pos: np.ndarray, rotvec: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, 3] = pos
    if np.linalg.norm(rotvec) > 1e-9:
        T[:3, :3] = R.from_rotvec(rotvec).as_matrix()
    return T


def _normalize_unit(raw: np.ndarray, conv: GripperConvention) -> np.ndarray:
    span = conv.open_at - conv.closed_at
    # span == 0 already rejected by GripperConvention.__post_init__
    return np.clip((raw - conv.closed_at) / span, 0.0, 1.0).astype(np.float32)


def _resolve_raw_gripper_column(table: pa.Table, layout: ProprioLayout) -> np.ndarray:
    if layout.gripper_via_column not in table.column_names:
        raise ValueError(
            f"layout names gripper_via_column={layout.gripper_via_column!r} "
            f"but parquet has no such column (have: {sorted(table.column_names)})"
        )
    col = table.column(layout.gripper_via_column)
    if pa.types.is_list(col.type) or pa.types.is_fixed_size_list(col.type):
        rows = col.to_pylist()
        idx = layout.gripper_index_in_column
        out = np.empty(len(rows), dtype=np.float64)
        for r, row in enumerate(rows):
            if row is None or len(row) <= idx:
                raise ValueError(
                    f"row {r} of {layout.gripper_via_column}: missing or too short "
                    f"for gripper_index_in_column={idx} (len="
                    f"{None if row is None else len(row)})"
                )
            out[r] = row[idx]
        return out
    if layout.gripper_index_in_column != 0:
        raise ValueError(
            f"scalar column {layout.gripper_via_column} cannot have "
            f"gripper_index_in_column != 0"
        )
    return np.asarray(col.to_pylist(), dtype=np.float64)


def _build_observation_state(table: pa.Table, layout: ProprioLayout) -> np.ndarray:
    """Concatenate the adapter-declared columns row-by-row, verbatim.

    Validates: every layout column exists in the table, list columns have
    consistent (non-ragged) widths, and concatenated dim matches
    len(layout.output_names).
    """
    cols: list[np.ndarray] = []
    for name in layout.columns:
        if name not in table.column_names:
            raise ValueError(
                f"layout column {name!r} not in parquet "
                f"(have: {sorted(table.column_names)})"
            )
        col = table.column(name)
        if pa.types.is_list(col.type) or pa.types.is_fixed_size_list(col.type):
            rows = col.to_pylist()
            if any(r is None for r in rows):
                raise ValueError(f"null row in list column {name}")
            widths = {len(r) for r in rows}
            if len(widths) != 1:
                raise ValueError(
                    f"ragged widths in list column {name}: {sorted(widths)}"
                )
            cols.append(np.asarray(rows, dtype=np.float32))
        else:
            cols.append(np.asarray(col.to_pylist(), dtype=np.float32)[:, None])
    out = np.concatenate(cols, axis=1)
    if out.shape[1] != len(layout.output_names):
        raise ValueError(
            f"concatenated proprio dim {out.shape[1]} != "
            f"len(output_names)={len(layout.output_names)} for layout "
            f"columns={layout.columns}"
        )
    return out


def convert_episode_table(
    *,
    table: pa.Table,
    instruction_text: str,
    gripper_convention: GripperConvention,
    proprio_layout: ProprioLayout,
) -> ConvertedEpisode:
    """Return a new pa.Table in VLA-compat schema.

    Output:
      - action: list<float32>[7] = [Δxyz(m), Δrxryrz(axis-angle rad), gripper([0,1])]
      - observation.state: list<float32>[N_proprio_robot] = adapter-declared concat
      - language_instruction: string repeated per row
      - passthrough columns (timestamp, frame_index, episode_index, index,
        task_index, observation.images.*.video_frame_index/t_mono_ns)

    Episode of n input rows produces n-1 output rows. The last frame is
    dropped (no obs[t]→obs[t+1] delta available); see spec §4.
    """
    n = table.num_rows
    if n < 2:
        raise ValueError(f"episode too short for delta computation: n={n}")
    missing = [c for c in _REQUIRED_INPUT_COLUMNS if c not in table.column_names]
    if missing:
        raise ValueError(
            f"convert_episode_table missing required columns: {missing}"
        )
    out_n = n - 1

    ee_pos = np.asarray(
        table.column("observation.state.ee_pos").to_pylist(), dtype=np.float64,
    )
    ee_rot = np.asarray(
        table.column("observation.state.ee_rotvec").to_pylist(), dtype=np.float64,
    )
    if not (np.isfinite(ee_pos).all() and np.isfinite(ee_rot).all()):
        raise ValueError("non-finite values in observation.state.ee_pos/ee_rotvec")

    actions = np.zeros((out_n, 7), dtype=np.float32)
    for t in range(out_n):
        T_curr = _to_T(ee_pos[t], ee_rot[t])
        T_next = _to_T(ee_pos[t + 1], ee_rot[t + 1])
        T_delta = np.linalg.inv(T_curr) @ T_next
        actions[t, 0:3] = T_delta[:3, 3]
        rotvec = R.from_matrix(T_delta[:3, :3]).as_rotvec()
        rmag = float(np.linalg.norm(rotvec))
        if rmag > _ROT_DELTA_SANITY_RAD:
            raise ValueError(
                f"per-step rotation delta {rmag:.3f} rad at t={t} exceeds "
                f"{_ROT_DELTA_SANITY_RAD} rad sanity bound — likely frame "
                f"mismatch or bad input data, not real motion"
            )
        actions[t, 3:6] = rotvec

    obs_state_full = _build_observation_state(table, proprio_layout).astype(np.float32)
    if not np.isfinite(obs_state_full).all():
        raise ValueError("non-finite values in observation.state columns")
    obs_state = obs_state_full[:out_n]

    raw_gripper = _resolve_raw_gripper_column(table, proprio_layout)
    if not np.isfinite(raw_gripper).all():
        raise ValueError("non-finite values in gripper column")
    actions[:, 6] = _normalize_unit(raw_gripper[:out_n], gripper_convention)

    arrays: dict[str, pa.Array] = {
        "action": pa.array(actions.tolist(), type=pa.list_(pa.float32(), 7)),
        "observation.state": pa.array(
            obs_state.tolist(),
            type=pa.list_(pa.float32(), obs_state.shape[1]),
        ),
        "language_instruction": pa.array(
            [instruction_text] * out_n, type=pa.string()
        ),
    }
    for col in _PASSTHROUGH_COLUMNS:
        if col in table.column_names:
            arrays[col] = table.column(col).slice(0, out_n)
    # Per-camera video frame index / t_mono_ns columns (passthrough, sliced).
    for name in table.column_names:
        if name.startswith("observation.images.") and (
            name.endswith(".video_frame_index") or name.endswith(".t_mono_ns")
        ):
            arrays[name] = table.column(name).slice(0, out_n)

    # info.json declares timestamp float32; ensure cast even when input came
    # from older recordings written before pending.finalize cast.
    if "timestamp" in arrays:
        arrays["timestamp"] = arrays["timestamp"].cast(pa.float32())

    return ConvertedEpisode(table=pa.table(arrays))
