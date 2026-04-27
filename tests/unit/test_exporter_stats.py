import json

import numpy as np
import pyarrow as pa
import pytest

from mimicrec.datasets.exporters.stats import compute_action_stats


def _converted(action_rows: list[list[float]]) -> pa.Table:
    return pa.table({
        "action": pa.array(action_rows, type=pa.list_(pa.float32(), 7)),
    })


def test_mean_and_std_over_single_episode():
    t = _converted([[0, 0, 0, 0, 0, 0, 0], [2, 2, 2, 2, 2, 2, 2]])
    out = compute_action_stats([t])
    np.testing.assert_allclose(out["mean"], [1.0] * 7, atol=1e-6)
    np.testing.assert_allclose(out["std"], [1.0] * 7, atol=1e-6)


def test_combined_across_episodes():
    a = _converted([[0]*7, [2]*7])
    b = _converted([[4]*7, [6]*7])
    out = compute_action_stats([a, b])
    np.testing.assert_allclose(out["mean"], [3.0]*7, atol=1e-6)
    # population std for [0,2,4,6] = sqrt(5) ≈ 2.236
    np.testing.assert_allclose(out["std"], [np.std([0,2,4,6])]*7, atol=1e-6)


def test_returns_serializable_floats():
    t = _converted([[1]*7, [2]*7])
    out = compute_action_stats([t])
    s = json.dumps(out)
    assert isinstance(s, str)
    assert "mean" in s and "std" in s


def test_empty_input_raises():
    with pytest.raises(ValueError):
        compute_action_stats([])


def test_std_floor_avoids_zero_division():
    # All identical rows — std would be 0; we floor at 1e-6 to match Normalizer.fit.
    t = _converted([[1]*7] * 5)
    out = compute_action_stats([t])
    assert all(s >= 1e-6 for s in out["std"])
