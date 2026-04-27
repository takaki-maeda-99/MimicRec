"""Compute action_stats.json over VLA-compat episode tables (pure)."""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pyarrow as pa

_STD_FLOOR = 1e-6


def compute_action_stats(tables: Iterable[pa.Table]) -> dict[str, list[float]]:
    """Compute population mean/std over the ``action`` column across tables.

    Returns ``{"mean": [...], "std": [...]}`` (length-7 list[float]).
    Matches the format ``vla_gemma4.data.normalizer.Normalizer.load`` expects.
    """
    rows: list[list[float]] = []
    for t in tables:
        rows.extend(t.column("action").to_pylist())
    if not rows:
        raise ValueError("compute_action_stats: no rows across tables")
    arr = np.asarray(rows, dtype=np.float64)
    mean = arr.mean(axis=0)
    std = arr.std(axis=0)
    std = np.maximum(std, _STD_FLOOR)
    return {"mean": [float(x) for x in mean], "std": [float(x) for x in std]}
