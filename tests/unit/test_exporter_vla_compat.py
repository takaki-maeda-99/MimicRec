import math

import numpy as np
import pyarrow as pa
import pytest
from scipy.spatial.transform import Rotation as R

from mimicrec.adapters.types import GripperConvention, ProprioLayout
from mimicrec.datasets.exporters.vla_compat import (
    convert_episode_table,
    ConvertedEpisode,
)


SO101_LAYOUT = ProprioLayout(
    columns=("observation.state.joint_pos",),
    output_names=("shoulder_pan", "shoulder_lift", "elbow_flex",
                  "wrist_flex", "wrist_roll", "gripper"),
    gripper_via_column="observation.state.joint_pos",
    gripper_index_in_column=5,
)

REBOT_LAYOUT = ProprioLayout(
    columns=("observation.state.joint_pos", "observation.state.gripper_pos"),
    output_names=("joint1", "joint2", "join3", "joint4", "joint5", "joint6", "gripper"),
    gripper_via_column="observation.state.gripper_pos",
    gripper_index_in_column=0,
)

SO101_CONV = GripperConvention(closed_at=0.0, open_at=100.0)
REBOT_CONV = GripperConvention(closed_at=1.0, open_at=0.0)


def _so101_table(
    n: int,
    *,
    ee_pos=None, ee_rot=None, joint_pos=None,
) -> pa.Table:
    if ee_pos is None:
        ee_pos = [[0.1 + 0.001 * i, 0.2, 0.3] for i in range(n)]
    if ee_rot is None:
        ee_rot = [[0.0, 0.0, 0.0] for _ in range(n)]
    if joint_pos is None:
        joint_pos = [[0.1 * i, 0.2, 0.3, 0.4, 0.5, 50.0] for i in range(n)]
    return pa.table({
        "observation.state.ee_pos": ee_pos,
        "observation.state.ee_rotvec": ee_rot,
        "observation.state.joint_pos": joint_pos,
        "observation.state.gripper_pos": [j[5] for j in joint_pos],
        "frame_index": list(range(n)),
        "episode_index": [0] * n,
        "index": list(range(n)),
        "task_index": [0] * n,
        "timestamp": [i / 15.0 for i in range(n)],
    })


def _rebot_table(
    n: int,
    *,
    ee_pos=None, ee_rot=None, joint_pos=None, gripper_pos=None,
) -> pa.Table:
    if ee_pos is None:
        ee_pos = [[0.1 + 0.001 * i, 0.2, 0.3] for i in range(n)]
    if ee_rot is None:
        ee_rot = [[0.0, 0.0, 0.0] for _ in range(n)]
    if joint_pos is None:
        joint_pos = [[0.1, 0.2, 0.3, 0.4, 0.5, 0.6] for _ in range(n)]
    if gripper_pos is None:
        gripper_pos = [0.5 for _ in range(n)]
    return pa.table({
        "observation.state.ee_pos": ee_pos,
        "observation.state.ee_rotvec": ee_rot,
        "observation.state.joint_pos": joint_pos,
        "observation.state.gripper_pos": gripper_pos,
        "frame_index": list(range(n)),
        "episode_index": [0] * n,
        "index": list(range(n)),
        "task_index": [0] * n,
        "timestamp": [i / 15.0 for i in range(n)],
    })


def test_action_is_ee_delta_with_gripper_in_unit_range():
    table = _so101_table(n=4)
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    actions = np.asarray(out.table.column("action").to_pylist())
    assert actions.shape == (3, 7)
    assert (actions[:, 6] >= 0).all() and (actions[:, 6] <= 1).all()


def test_action_uses_ee_local_frame_via_matrix_compose():
    rng = np.random.default_rng(0)
    pos = rng.normal(scale=0.05, size=(2, 3))
    rot = rng.normal(scale=0.05, size=(2, 3))
    table = _so101_table(n=2, ee_pos=pos.tolist(), ee_rot=rot.tolist())
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    a = np.asarray(out.table.column("action").to_pylist())[0]
    T_curr = np.eye(4); T_curr[:3, 3] = pos[0]
    T_curr[:3, :3] = R.from_rotvec(rot[0]).as_matrix()
    T_next_expected = np.eye(4); T_next_expected[:3, 3] = pos[1]
    T_next_expected[:3, :3] = R.from_rotvec(rot[1]).as_matrix()
    T_delta = np.eye(4); T_delta[:3, 3] = a[0:3]
    T_delta[:3, :3] = R.from_rotvec(a[3:6]).as_matrix()
    T_next_actual = T_curr @ T_delta
    np.testing.assert_allclose(T_next_actual[:3, 3], T_next_expected[:3, 3], atol=1e-6)
    np.testing.assert_allclose(T_next_actual[:3, :3], T_next_expected[:3, :3], atol=1e-6)


def test_rotation_delta_above_one_rad_raises_sanity():
    pos = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    rot = [[0.0, 0.0, 0.0], [0.0, 0.0, 1.1]]
    table = _so101_table(n=2, ee_pos=pos, ee_rot=rot)
    with pytest.raises(ValueError, match="exceeds .* sanity bound"):
        convert_episode_table(
            table=table, instruction_text="x",
            gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
        )


def test_rotation_delta_near_zero_returns_small_axisangle():
    pos = [[0.0]*3, [0.0]*3]
    rot = [[0.0]*3, [1e-10, 1e-10, 1e-10]]
    table = _so101_table(n=2, ee_pos=pos, ee_rot=rot)
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    a = np.asarray(out.table.column("action").to_pylist())[0]
    assert np.linalg.norm(a[3:6]) < 1e-6


def test_export_drops_last_frame_episode_n_to_n_minus_1():
    out = convert_episode_table(
        table=_so101_table(n=10), instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    assert out.table.num_rows == 9


def test_episode_n_equals_2_outputs_one_row():
    out = convert_episode_table(
        table=_so101_table(n=2), instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    assert out.table.num_rows == 1


def test_episode_n_equals_1_raises():
    with pytest.raises(ValueError, match="too short"):
        convert_episode_table(
            table=_so101_table(n=1), instruction_text="x",
            gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
        )


def test_gripper_normalized_so101_convention():
    joint_pos = [[0.0]*5 + [0.0], [0.0]*5 + [50.0], [0.0]*5 + [100.0]]
    table = _so101_table(n=3, joint_pos=joint_pos)
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    g = np.asarray(out.table.column("action").to_pylist())[:, 6]
    np.testing.assert_allclose(g, [0.0, 0.5])


def test_gripper_normalized_rebot_inverted_convention():
    table = _rebot_table(n=3, gripper_pos=[1.0, 0.5, 0.0])
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=REBOT_CONV, proprio_layout=REBOT_LAYOUT,
    )
    g = np.asarray(out.table.column("action").to_pylist())[:, 6]
    np.testing.assert_allclose(g, [0.0, 0.5])


def test_gripper_clipped_when_raw_overshoots():
    joint_pos = [[0.0]*5 + [-10.0], [0.0]*5 + [120.0]]
    table = _so101_table(n=2, joint_pos=joint_pos)
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    g = np.asarray(out.table.column("action").to_pylist())[:, 6]
    assert g[0] == 0.0


def test_observation_state_so101_is_joint_pos_verbatim():
    table = _so101_table(n=3)
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    obs = np.asarray(out.table.column("observation.state").to_pylist())
    assert obs.shape == (2, 6)
    expected = np.asarray(table.column("observation.state.joint_pos").to_pylist())[:2]
    np.testing.assert_allclose(obs, expected)


def test_observation_state_rebot_concatenates_joint_pos_and_gripper_pos():
    table = _rebot_table(n=3)
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=REBOT_CONV, proprio_layout=REBOT_LAYOUT,
    )
    obs = np.asarray(out.table.column("observation.state").to_pylist())
    assert obs.shape == (2, 7)
    np.testing.assert_allclose(obs[:, -1], [0.5, 0.5])


def test_observation_state_missing_layout_column_raises_value_error():
    table = _so101_table(n=3)
    table = table.drop_columns(["observation.state.joint_pos"])
    with pytest.raises(ValueError, match="not in parquet"):
        convert_episode_table(
            table=table, instruction_text="x",
            gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
        )


def test_observation_state_ragged_list_column_raises_value_error():
    n = 3
    ragged = [[0.0]*6, [0.0]*5, [0.0]*6]
    table = pa.table({
        "observation.state.ee_pos": [[0.0]*3]*n,
        "observation.state.ee_rotvec": [[0.0]*3]*n,
        "observation.state.joint_pos": ragged,
        "observation.state.gripper_pos": [0.0]*n,
        "frame_index": list(range(n)),
        "episode_index": [0]*n, "index": list(range(n)), "task_index": [0]*n,
        "timestamp": [i/15.0 for i in range(n)],
    })
    with pytest.raises(ValueError, match="ragged widths"):
        convert_episode_table(
            table=table, instruction_text="x",
            gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
        )


def test_observation_state_dim_mismatch_with_output_names_raises_value_error():
    bad_layout = ProprioLayout(
        columns=("observation.state.joint_pos",),
        output_names=("a", "b", "c", "d", "e"),
        gripper_via_column="observation.state.joint_pos",
        gripper_index_in_column=4,
    )
    with pytest.raises(ValueError, match="!= len\\(output_names\\)"):
        convert_episode_table(
            table=_so101_table(n=3), instruction_text="x",
            gripper_convention=SO101_CONV, proprio_layout=bad_layout,
        )


def test_resolve_gripper_index_out_of_bounds_raises_value_error():
    bad_layout = ProprioLayout(
        columns=("observation.state.joint_pos",),
        output_names=("a",) * 6,
        gripper_via_column="observation.state.joint_pos",
        gripper_index_in_column=99,
    )
    with pytest.raises(ValueError, match="missing or too short"):
        convert_episode_table(
            table=_so101_table(n=3), instruction_text="x",
            gripper_convention=SO101_CONV, proprio_layout=bad_layout,
        )


def test_resolve_gripper_scalar_column_with_nonzero_index_raises_value_error():
    bad_layout = ProprioLayout(
        columns=("observation.state.joint_pos", "observation.state.gripper_pos"),
        output_names=("j1","j2","join3","j4","j5","j6","gripper"),
        gripper_via_column="observation.state.gripper_pos",
        gripper_index_in_column=1,
    )
    with pytest.raises(ValueError, match="cannot have gripper_index_in_column != 0"):
        convert_episode_table(
            table=_rebot_table(n=3), instruction_text="x",
            gripper_convention=REBOT_CONV, proprio_layout=bad_layout,
        )


def test_rotation_delta_below_sanity_bound_passes_reconstruction():
    """Construct a relative rotation just below the 1-rad sanity bound
    (well below π); verify it survives extraction + matrix reconstruction."""
    pos = [[0.0]*3, [0.0]*3]
    rot = [[0.0]*3, [0.0, 0.0, 0.9]]
    table = _so101_table(n=2, ee_pos=pos, ee_rot=rot)
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    a = np.asarray(out.table.column("action").to_pylist())[0]
    T_curr = np.eye(4)
    T_next_expected = np.eye(4); T_next_expected[:3, :3] = R.from_rotvec(rot[1]).as_matrix()
    T_delta = np.eye(4); T_delta[:3, 3] = a[0:3]
    T_delta[:3, :3] = R.from_rotvec(a[3:6]).as_matrix()
    T_next_actual = T_curr @ T_delta
    np.testing.assert_allclose(T_next_actual[:3, :3], T_next_expected[:3, :3], atol=1e-6)


def test_non_finite_inputs_raise():
    pos = [[float("nan"), 0, 0], [0, 0, 0]]
    rot = [[0.0]*3, [0.0]*3]
    table = _so101_table(n=2, ee_pos=pos, ee_rot=rot)
    with pytest.raises(ValueError, match="non-finite"):
        convert_episode_table(
            table=table, instruction_text="x",
            gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
        )


def test_output_carries_language_instruction_per_row():
    out = convert_episode_table(
        table=_so101_table(n=4), instruction_text="hello",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    li = out.table.column("language_instruction").to_pylist()
    assert li == ["hello"] * 3
