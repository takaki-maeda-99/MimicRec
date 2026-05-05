import numpy as np
import pyarrow as pa

from mimicrec.datasets.exporters.stats import compute_stats


def _table(actions: list[list[float]], proprios: list[list[float]]) -> pa.Table:
    return pa.table({
        "action": pa.array(actions, type=pa.list_(pa.float32(), len(actions[0]))),
        "observation.state": pa.array(
            proprios, type=pa.list_(pa.float32(), len(proprios[0])),
        ),
    })


def _seven(action: list[float]) -> list[float]:
    assert len(action) == 7
    return action


def test_compute_stats_returns_three_blocks():
    actions = [[0.0]*7, [1.0]*7]
    proprios = [[0.0]*6, [1.0]*6]
    a_stats, a_q99, p_q99 = compute_stats([_table(actions, proprios)])
    assert "mean" in a_stats and "std" in a_stats and "convention" in a_stats
    assert "q01" in a_q99 and "q99" in a_q99 and "mask" in a_q99
    assert "q01" in p_q99 and "q99" in p_q99 and "mask" in p_q99


def test_action_stats_carries_convention_field():
    a_stats, _, _ = compute_stats([_table([[0.0]*7, [1.0]*7], [[0.0]*6, [1.0]*6])])
    assert a_stats["convention"] == "q99_derived_midpoint_halfrange"


def test_action_stats_mean_equals_midpoint_of_action_q99():
    rng = np.random.default_rng(0)
    actions = rng.normal(size=(200, 7)).tolist()
    a_stats, a_q99, _ = compute_stats([_table(actions, [[0.0]*6 for _ in actions])])
    midpoint = [(a + b) / 2 for a, b in zip(a_q99["q01"], a_q99["q99"])]
    np.testing.assert_allclose(a_stats["mean"], midpoint, atol=1e-9)


def test_action_stats_std_equals_half_range_of_action_q99():
    rng = np.random.default_rng(1)
    actions = rng.normal(size=(200, 7)).tolist()
    a_stats, a_q99, _ = compute_stats([_table(actions, [[0.0]*6 for _ in actions])])
    half_range = [max((b - a) / 2, 1e-6) for a, b in zip(a_q99["q01"], a_q99["q99"])]
    np.testing.assert_allclose(a_stats["std"], half_range, atol=1e-9)


def test_action_q99_mask_all_true_for_seven_dim_action():
    _, a_q99, _ = compute_stats([_table([[0.0]*7, [1.0]*7], [[0.0]*6, [1.0]*6])])
    assert a_q99["mask"] == [True] * 7


def test_proprio_q99_length_matches_per_robot_dim():
    rng = np.random.default_rng(2)
    proprios_so101 = rng.normal(size=(50, 6)).tolist()
    proprios_rebot = rng.normal(size=(50, 7)).tolist()
    actions = [[0.0]*7] * 50

    _, _, p_so101 = compute_stats([_table(actions, proprios_so101)])
    _, _, p_rebot = compute_stats([_table(actions, proprios_rebot)])
    assert len(p_so101["q01"]) == 6
    assert len(p_rebot["q01"]) == 7


def test_compute_stats_raises_on_no_rows():
    import pytest
    empty = pa.table({
        "action": pa.array([], type=pa.list_(pa.float32(), 7)),
        "observation.state": pa.array([], type=pa.list_(pa.float32(), 6)),
    })
    with pytest.raises(ValueError, match="no rows"):
        compute_stats([empty])
