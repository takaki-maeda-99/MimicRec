# LeRobot v3-Native Recording Schema

**Date:** 2026-04-29
**Status:** Draft (pending spec review + user approval)
**Scope:** Restructure MimicRec's recording write path so the raw v3 dataset is directly loadable by the upstream `LeRobotDataset` API, and remove the `vla_compat` export indirection.

## 1. Purpose

Today MimicRec records into a verbose, MimicRec-specific raw v3 schema (separate `observation.state.joint_pos`, `observation.state.joint_vel`, `action.joint_pos`, `action.gripper_pos`, etc.) and provides a `vla_compat` exporter that repacks it into a LeRobot-loadable form. The seven schema bugs fixed on 2026-04-28 made `vla_compat` output spec-compliant, but the **raw v3 itself is still not loadable** — `LeRobotDataset.load_hf_dataset()` raises `CastError` against the verbose columns.

The user's pipeline is `raw → LeRobot v3 (canonical) → HF Hub → StreamingLeRobotDataset → optional dataloader-side conversion`. For that to work, **raw v3 must equal LeRobot v3 native**. This spec collapses the two by writing the LeRobot-loadable schema directly at recording time and removing `vla_compat`.

A side-effect: SO-101's "gripper duplicated at action[5] and action[6]" bug is fixed by construction. SO-101 will have `dof=5` arm + a separately-tracked gripper, packed once into `action[6]`.

## 2. Scope

### In scope

- Recording writer emits the LeRobot v3 native schema (8 columns, packed action / observation.state, denormalized `language_instruction`).
- `parquet_row.sample_bundle_to_row` rewritten to produce that schema.
- Per-robot DOF determines `action.shape = [N]` where N = arm DOF + 1 gripper.
- SO-101 adapter restructure: `dof=5`, gripper carried separately on `RobotState.gripper_pos` and `RobotCommand.gripper`.
- `so_leader.py` mirror change so leader teleop produces `RobotCommand` with `q` of length 5 and `gripper` populated.
- Replay reader (`datasets/reader.py`) reads packed `action` column and splits joint vs gripper targets.
- `info.json` features auto-derived from robot config (action shape, observation.state shape, joint_names + ["gripper"]).
- Removal of `vla_compat`: deletes `exporters/{vla_compat,info_json,instructions,stats}.py`, the `ExportFormat` enum's `VLA_COMPAT` member, the `/api/datasets/{ds}/export` POST endpoint, the `ExportDatasetModal` frontend component, and `get_vla_dest_root`.
- Existing 33 episodes are discarded — no migration / backfill.

### Out of scope (deferred)

- HF Hub upload (separate brainstorm).
- Per-frame language_instruction templating (raw stores the literal task instruction; templating happens in the dataloader).
- Adding back ancillary observations (`joint_vel`, `joint_effort`, `ee_pos`, `ee_rotvec`) as declared optional features. They are simply dropped.
- Monotonic-time diagnostic columns (`tick_t_mono_ns`, `*.t_mono_ns`). Dropped.
- Action stats (`action_stats.json`) — dataloader normalizes at load time.
- Gripper unit conversion (raw stays in lerobot's `[0, 100]`; dataloader can map to `[-1, +1]` if needed).

## 3. Resulting on-disk layout

```
<dataset_root>/
├── meta/
│   ├── info.json          (codebase_version: v3.0; features = 8-column schema)
│   ├── tasks.parquet      (task / task_index / instruction — unchanged)
│   └── episodes/chunk-000/file-000.parquet  (per-episode meta incl. per-video)
├── data/
│   └── chunk-000/
│       └── episode_000000.parquet
└── videos/
    └── observation.images.<cam>/
        └── chunk-000/
            └── episode_000000.mp4
```

## 4. Per-frame parquet schema (data/chunk-XXX/episode_XXXXXX.parquet)

| Column | Type | Source / semantics |
|---|---|---|
| `action` | `float32[N]` | Concat: `bundle.action.q[0..Narm-1]` ⊕ `bundle.action.gripper`. Length N = robot DOF (arm) + 1. |
| `observation.state` | `float32[N]` | Concat: `state.joint_pos[0..Narm-1]` ⊕ `state.gripper_pos`. Same shape as action. |
| `language_instruction` | `string` | `tasks.parquet[task_index].instruction` literal, repeated per row. Empty string if instruction is null. Falls back to `tasks.parquet[task_index].task` (task name) if instruction is missing — emit one episode-level warning so it's visible. |
| `timestamp` | `float32` | `frame_index / fps`, computed in `pending.save()`. |
| `frame_index` | `int64` | Per-episode index 0..length-1. |
| `episode_index` | `int64` | Episode identifier. |
| `index` | `int64` | Dataset-absolute index = `dataset_from_index + frame_index`, computed in `pending.save()`. |
| `task_index` | `int64` | Reference into `tasks.parquet`. |

Exactly 8 columns. No `*.t_mono_ns`, no `*_vel`, no `*_effort`, no `*_ee_*`.

## 5. info.json features

```json
{
  "codebase_version": "v3.0",
  "fps": <fps>,
  "data_path": "data/chunk-{chunk_index:03d}/episode_{file_index:06d}.parquet",
  "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/episode_{file_index:06d}.mp4",
  "features": {
    "action": {"dtype": "float32", "shape": [N], "names": [<joint_names...>, "gripper"]},
    "observation.state": {"dtype": "float32", "shape": [N], "names": [<joint_names...>, "gripper"]},
    "language_instruction": {"dtype": "string", "shape": [1], "names": null},
    "timestamp": {"dtype": "float32", "shape": [1], "names": null},
    "frame_index": {"dtype": "int64", "shape": [1], "names": null},
    "episode_index": {"dtype": "int64", "shape": [1], "names": null},
    "index": {"dtype": "int64", "shape": [1], "names": null},
    "task_index": {"dtype": "int64", "shape": [1], "names": null},
    "observation.images.<cam>": {
      "dtype": "video", "shape": [H, W, 3], "names": ["height","width","channels"],
      "info": {"video.fps": <fps>, "video.codec": "libx264", ...}
    }
  }
}
```

`init_dataset(ds_root, fps, joint_names, camera_names)` is the single source of truth. Caller passes `joint_names` of length Narm (NO `"gripper"` appended); `init_dataset` appends `"gripper"` itself, sets `action.shape = observation.state.shape = [Narm + 1]`, and adds the `language_instruction` feature spec to the features dict explicitly. Today `init_dataset` writes neither `language_instruction` nor a packed `action` shape — both are added in this change.

## 6. Writer / pending flow

### `parquet_row.sample_bundle_to_row` (rewritten)

```python
def sample_bundle_to_row(
    bundle: SampleBundle,
    episode_start_t_mono_ns: int,
    *,
    instruction: str,
    fk_n_kin_joints: int | None = None,  # for adapters that pack gripper into q
    frame_index: int = 0,
    episode_index: int = 0,
    global_index: int = 0,
    task_index: int = 0,
) -> dict:
    # Observation: split arm joints + gripper into a single packed vector.
    s = bundle.state.value
    Narm = fk_n_kin_joints if fk_n_kin_joints is not None else s.joint_pos.shape[0]
    obs_arm = s.joint_pos[:Narm]
    # gripper fallback only fires for legacy adapters whose joint_pos still packs gripper.
    # After SO-101 is migrated, joint_pos.shape[0] == Narm and we never index past it.
    if s.gripper_pos is not None:
        obs_grip = float(s.gripper_pos)
    elif s.joint_pos.shape[0] > Narm:
        obs_grip = float(s.joint_pos[Narm])
    else:
        raise ValueError("missing gripper_pos and no slack joint to derive from")
    observation_state = np.concatenate([obs_arm, [obs_grip]]).astype(np.float32)

    # Action: same recipe applied to bundle.action.
    a_arm = bundle.action.q[:Narm]
    if bundle.action.gripper is not None:
        a_grip = float(bundle.action.gripper)
    elif bundle.action.q.shape[0] > Narm:
        a_grip = float(bundle.action.q[Narm])
    else:
        raise ValueError("missing action.gripper and no slack joint to derive from")
    action = np.concatenate([a_arm, [a_grip]]).astype(np.float32)

    return {
        "action": action,
        "observation.state": observation_state,
        "language_instruction": instruction,
        "timestamp": 0.0,         # placeholder, pending.save() rewrites
        "frame_index": frame_index,
        "episode_index": episode_index,
        "index": 0,                # placeholder, pending.save() rewrites
        "task_index": task_index,
    }
```

The existing observation-side EE preference logic (state.ee_pos before fk.pose) and the action-side FK fallback are removed; ee_pos / ee_rotvec are no longer written.

`fk_n_kin_joints` is plumbed from `FKService` when available so SO-101 (which today packs gripper into q[5]) keeps working through the transition. Once SO-101 adapter is fixed (Section 7), q always has length Narm and the parameter becomes unnecessary — but we keep it as a safety net for adapters that haven't been migrated.

### `writer.run_writer` (signature change)

`run_writer` gains one parameter:
- `instruction_provider: Callable[[], str]` — closure capturing the current pending episode's instruction string. Resolved at episode start (when the API caller picks a task) and held for the duration of that pending episode.

Per row, writer calls `instruction_provider()` and passes the result into `sample_bundle_to_row`. This avoids plumbing a per-row `task_index → instruction` lookup table since MimicRec records one task per episode.

`task_index` itself is still hardcoded to `0` per row in this iteration (matching today's writer.py). Replacing it with a real index is out of scope for this spec — the recording schema needs to declare and write the column, but multi-task-per-episode is a separate feature.

### `pending.PendingEpisode.save` (no signature change)

Already does timestamp/index rewrites at save time. No changes needed there.

### Removal of dead state

`writer.run_writer` already had `video_frame_index` removed (2026-04-28). The remaining `bundle.frames` flow (used for mp4 frame writing in `pending.append_row`) stays.

## 7. SO-101 adapter restructure

### `adapters/so101.py`

Changes:
- `dof = 5` (was 6).
- `JOINT_NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]` (drop `"gripper"`).
- `read_state()` reads all 6 lerobot motor positions, splits the 6th into a separate `RobotState.gripper_pos: float`, and returns `joint_pos: float32[5]`.
- `send_joint_command(q: np.ndarray, gripper: float | None = None)` — new keyword-only `gripper` parameter. Builds the 6-key lerobot action dict by recombining `q[5]` with the explicit `gripper` value. If `gripper is None`, the command does not move the gripper (preserves last commanded position; lerobot's `send_action` requires all keys, so we re-read current to fill).

### `adapters/so_leader.py`

Mirror: `read_action()` returns a 5-element `target_joint_pos` plus a separate `gripper` value on the `TeleopAction`.

### `types.TeleopAction` (NEW field)

Add `gripper: float | None = None`. Today `TeleopAction` only carries `target_joint_pos` / `ee_delta`; the leader has nowhere to put a gripper command. With the new field, the leader populates it and the mapper forwards it.

### `mappers/identity.py` (forward gripper)

`IdentityMapper.map(action: TeleopAction)` currently builds `RobotCommand(q=action.target_joint_pos.copy())`. Change to also forward gripper:

```python
return RobotCommand(
    q=action.target_joint_pos.copy(),
    gripper=action.gripper,
)
```

### `types.RobotState` / `types.RobotCommand`

Already have optional `gripper_pos` / `gripper`. No type change needed; the contract becomes "always populated for robots that have a gripper".

### Dispatcher / gripper routing

Today `session/dispatcher.py` routes the gripper command via a **separate** `adapter.send_gripper_command(cmd.gripper)` call (used by `rebotarm_zmq.py`). SO-101 has no gripper-specific method — gripper rides inside the 6-element joint command. To keep the dispatcher uniform, this spec adopts:

**Universal contract:** every adapter's `send_joint_command(q, *, gripper=None)` accepts an optional gripper kwarg. Adapters are free to ignore it (gripperless arms) or split internally (reBotArm calls its existing internal gripper path). The dispatcher passes `gripper=cmd.gripper` exactly once per tick and **deletes the separate `send_gripper_command` branch**.

- `adapters/so101.py::send_joint_command(q, *, gripper=None)` — recombines q[5] and gripper into the 6-key lerobot dict.
- `adapters/rebotarm_zmq.py::send_joint_command(q, *, gripper=None)` — internally forwards to its existing gripper path when `gripper is not None`. The standalone `send_gripper_command` method becomes dead code and is removed.
- Any other adapter — receives the kwarg but may ignore it.

### Calibration cache

SO-101's lerobot calibration file (`~/.cache/huggingface/lerobot/calibration/...`) declares all 6 motor names including the gripper motor. **No change** — that's the lerobot-side hardware mapping and unaffected by how MimicRec splits joints internally.

## 8. Replay reader

### `datasets/reader.py:load_replay_trajectory`

```python
table = pq.read_table(parquet_path)
action_col = table.column("action").to_pylist()      # list[list[float]] of shape (n, N)
action_arr = np.array(action_col, dtype=np.float32)
joint_targets = action_arr[:, :-1]                   # arm joints
gripper_targets = action_arr[:, -1].astype(np.float32)
```

Backward-compat fallback for hand-teach recordings (the `joint_pos.shape[1] > 6` path) is removed — old data has been discarded.

## 9. Removed components

| Path | Reason |
|---|---|
| `backend/mimicrec/datasets/exporters/vla_compat.py` | Schema is now the recording schema; conversion is the identity. |
| `backend/mimicrec/datasets/exporters/info_json.py` | `to_vla_info` is dead. |
| `backend/mimicrec/datasets/exporters/instructions.py` | Templating moves to dataloader. |
| `backend/mimicrec/datasets/exporters/stats.py` | Action stats computed at load time by dataloader. |
| `backend/mimicrec/datasets/exporters/orchestrator.py` | Remaining `_export_v3_native` is identical to `archive.build_archive_stream` writing to disk; collapse callers to use `archive.py` and download zip. |
| `backend/mimicrec/datasets/exporters/errors.py` | DestinationExistsError unused after orchestrator removal. |
| `backend/mimicrec/api/schemas.py::ExportFormat`, `ExportRequest`, `ExportResponse`, `DEFAULT_INSTRUCTION_TEMPLATE` | No format choice exposed. |
| `backend/mimicrec/api/routes/datasets.py::POST /api/datasets/{ds}/export` | Replaced by existing zip download. |
| `backend/mimicrec/api/deps.py::get_vla_dest_root` | No external dest. |
| `frontend/src/components/ExportDatasetModal*` | Datasets page reverts to plain "Download" link. |
| `frontend/src/api/types.ts::ExportFormat` type | No format choice exposed. |
| `frontend/src/api/queries.ts::useExportDataset` mutation | Removed alongside the route. |
| `backend/mimicrec/api/routes/datasets.py::export_dataset` POST handler + its imports (`export_dataset_to_local`, `DestinationExistsError`, `ExportRequest`, `ExportResponse`, `ExportFormat`) | Replaced by existing `archive` zip download. |

Tests that exercise these (`test_exporter_*.py`, `test_vla_compat_roundtrip.py`, the `format=vla_compat` route tests) are deleted alongside.

## 10. Tests

### New / updated unit tests

- `test_parquet_row.py`: assert row has exactly 8 keys, `action` and `observation.state` are np.float32 of length N (parametrize N=6 SO-101, N=7 reBot), `language_instruction` matches the passed instruction.
- `test_pending_episode.py`: existing `test_saved_*` tests stay green with the new schema; add a check that the saved parquet schema matches `info.json` features (catch dtype drift).
- `test_so101_adapter.py` (new or augmented): `read_state()` returns `joint_pos.shape == (5,)` and a non-None `gripper_pos`; `send_joint_command(q, gripper=g)` invokes lerobot with the right 6-key dict.
- `test_so_leader_adapter.py`: same shape changes for the leader.
- `test_replay_reader.py` (or update `test_dataset_reader_tombstones.py`): `load_replay_trajectory` reads packed action and returns 5-wide `joint_targets` + 1-wide `gripper_targets` for an SO-101 recording.

### Deleted tests

- `tests/unit/test_exporter_vla_compat.py`
- `tests/unit/test_exporter_info_json.py`
- `tests/unit/test_exporter_instructions.py`
- `tests/unit/test_exporter_stats.py`
- `tests/unit/test_exporter_orchestrator.py` (or trimmed to `archive`-only assertions)
- `tests/integration/test_vla_compat_roundtrip.py`
- API route tests for the removed `/export` endpoint.

### Integration test

End-to-end: record one mock episode (mock adapter with N=2 for fast tests) → assert `LeRobotDataset(repo_id="local/x", root=..., episodes=[0], download_videos=False)` constructs without `CastError` and returns `num_episodes == 1`. Skip if `lerobot` import fails (matches existing `pytest.importorskip("lerobot")` pattern).

## 11. Migration

The existing 33 SO-101 episodes are discarded by the user. No backfill script. After this change lands, new recordings start fresh with the LeRobot-native schema.

## 12. Risks / open issues

- **lerobot `send_action` requires all 6 keys**: when `RobotCommand.gripper is None` (e.g. replay paths reading older recordings — though those are discarded — or hand-teach where the user did not intend to drive gripper), `send_joint_command` must fill it. Plan: read current gripper position via `read_state()` and send that — gripper holds. After this change, recordings always carry gripper in `action[N-1]`, so replay's `gripper_targets` will always be populated for SO-101/reBot. Tests must cover the `RobotCommand.gripper is None` defensive branch.
- **Empty instruction**: tasks.parquet may have null/empty instruction. Falling back to task name + episode-level warning is consistent with the old `vla_compat` behavior; keep that single warning path. The `instruction_provider` closure performs this resolution at episode start.
- **Robots without grippers**: out of scope; both supported robots (SO-101, reBot) have grippers. If added later, action shape becomes `[Narm]` and `gripper_pos` is omitted; that's a follow-up.
- **Frontend deletion timing**: removing `ExportDatasetModal` while the user has it open in their browser will yield a stale UI. Acceptable for single-user dev tool.
- **`EpisodeSummary.task_index`**: this field on the API response (`api/schemas.py`) is unrelated to the export removal; it stays.

## 13. Acceptance criteria

1. After `git pull`, recording one episode on the mock adapter and one on SO-101 produces parquets whose schema is exactly the 8 columns in Section 4, with `action` shape `[Ntotal]` matching robot DOF.
2. `LeRobotDataset(repo_id, root=<dataset_root>, episodes=[0], download_videos=False)` constructs without raising. (Video decode requires user's ffmpeg; not part of CI.)
3. SO-101 replay of a recorded episode drives both arm joints and gripper correctly (verified manually on hardware after change).
4. `pytest tests/` passes with the deleted tests removed and the new tests added.
5. `find backend/mimicrec/datasets/exporters` returns only `__init__.py` (or the dir is removed entirely).
6. The Datasets page in the frontend shows a single "Download" link per dataset (no Export button / modal).
