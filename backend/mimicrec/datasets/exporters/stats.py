"""Compute action_stats / action_stats_q99 / proprio_stats_q99 over
VLA-compat episode tables (pure)."""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pyarrow as pa

_STD_FLOOR = 1e-6
_ACTION_STATS_CONVENTION = "q99_derived_midpoint_halfrange"


def compute_stats(tables: Iterable[pa.Table]) -> tuple[dict, dict, dict]:
    """Return (action_stats, action_q99, proprio_q99).

    action_stats has `mean`, `std`, AND a `convention` metadata field. The
    mean/std are NOT the actual mean/std of the action distribution; they
    are derived from q01/q99 so the existing decoder's
    `physical = mean + arr * std` formula correctly inverts a model output
    `arr` in [-1,+1] that came from BOUNDS_Q99 normalization at training
    time. See spec §6 for the math.
    """
    action_rows: list[list[float]] = []
    proprio_rows: list[list[float]] = []
    for t in tables:
        action_rows.extend(t.column("action").to_pylist())
        proprio_rows.extend(t.column("observation.state").to_pylist())
    if not action_rows:
        raise ValueError("compute_stats: no rows across tables")

    arr_a = np.asarray(action_rows, dtype=np.float64)    # [N, 7]
    arr_p = np.asarray(proprio_rows, dtype=np.float64)   # [N, D_prop_robot]

    a_q01 = np.quantile(arr_a, 0.01, axis=0)
    a_q99 = np.quantile(arr_a, 0.99, axis=0)
    a_midpoint = (a_q99 + a_q01) / 2.0
    a_half_range = np.maximum((a_q99 - a_q01) / 2.0, _STD_FLOOR)

    p_q01 = np.quantile(arr_p, 0.01, axis=0)
    p_q99 = np.quantile(arr_p, 0.99, axis=0)

    action_stats = {
        "mean": a_midpoint.tolist(),
        "std": a_half_range.tolist(),
        "convention": _ACTION_STATS_CONVENTION,
    }
    action_q99 = {
        "q01": a_q01.tolist(),
        "q99": a_q99.tolist(),
        "mask": [True] * 7,
    }
    proprio_q99 = {
        "q01": p_q01.tolist(),
        "q99": p_q99.tolist(),
        "mask": [True] * arr_p.shape[1],
    }
    return action_stats, action_q99, proprio_q99
