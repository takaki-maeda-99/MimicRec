# VLA-Compat Export: EE-Delta Action Format

**Status:** design — pending implementation plan
**Author:** takaki, w/ Claude (Opus 4.7) and Codex (gpt-5.5) review
**Scope:** MimicRec exporter + the minimum recording-layer change required to populate `robot_type` / proprio composition / gripper convention in fresh `info.json` files. Inference contract YAML, X-VLA-Adapter side dataset config, and `SO101Adapter.read_state` proprio fix are explicit follow-ups.

> **Hard prerequisites.** This PR produces the parquet export and stats files the **future X-VLA-side dataset loader will consume**; the loader itself does not yet exist (Non-goals item: X-VLA-Adapter side dataset config). It is also **not deployable for inference** until the inference contract YAML follow-up (§Non-goals) ships and confirms operator-facing docs.
>
> Math expectation: the training-side normalization is BOUNDS_Q99 — `arr = clip(2 * (physical - q01) / (q99 - q01) - 1, -1, +1)`, model output `arr ∈ [-1,+1]`. This PR's `action_stats.json` is **derived from q01/q99** (`mean = (q01+q99)/2`, `std = (q99-q01)/2`) so that the existing decoder's `physical = mean + arr * std` formula is the exact inverse: `midpoint + arr * half_range = q01 + (arr+1)/2 * (q99-q01)`. A `convention: "q99_derived_midpoint_halfrange"` metadata field in `action_stats.json` flags this. Do not point the live robot at a model trained from this export until the contract YAML follow-up confirms it is using the matching mode.

## Problem

The VLA-compat exporter (`backend/mimicrec/datasets/exporters/vla_compat.py`) writes:

```
action[i] = [joint_pos[0..5] (deg, absolute), 1.0 - gripper_raw/50.0]   # 7 floats
#           └─ joint space ─┘                 └─ gripper in [-1,+1] ─┘
```

Three bugs follow from this:

1. **Action space is wrong.** The VLA inference contract (`configs/inference/gemma_libero_v1.yaml`, validated by `inference/contract.py` + `inference/action_decoder.py`) and the X-VLA-Adapter trainer architecture (`X-VLA-Adapter/docs/architectures/x_vla_adapter.md`, A=7) both expect `action = [Δxyz, Δrxryrz, gripper]` in (m, axis-angle rad, [0,1]). The current export's joint-absolute degrees has no relationship to that — the decoder treats them as `ee_delta` and chains them as `T_next = T_curr · ΔT_local`, producing meter-scale jumps from degree-scale inputs.
2. **Gripper convention is reversed.** Current `[-1,+1]` with `+1=closed` vs target `[0,1]` with `0=closed`.
3. **Gripper normalization hard-coded for SO-101.** The `1.0 - raw/50.0` formula assumes `RANGE_0_100`. reBot data — recorded with `gripper_pos` as a normalized open-close command in `[0, 1]` (1=closed / 0=open, the controller-input value declared in `configs/mapper/so_to_rebotarm_ee.yaml`: `gripper_invert: true`, `out_min/max=0/1`; **not** a hardware-measured angle in radians) — is already getting garbage values exported.

## Goals (in scope)

1. **Action label** = `[ee_delta(6), gripper(1)]` in (m, axis-angle rad, [0,1] with 0=closed/1=open), `ee_local` frame, derived from `observation.state.ee_pos / ee_rotvec` already recorded in every existing episode (verified: 240/240 episodes have these columns).
2. **observation.state** = per-robot composition, declared by the adapter:
   - SO-101: `observation.state.joint_pos` verbatim (6-dim; index 5 is packed gripper, native lerobot semantic).
   - reBot: `observation.state.joint_pos` (6-dim arm joints) `||` `observation.state.gripper_pos` (1-dim) = 7-dim.
   No re-normalization at export time. The X-VLA-Adapter side handles per-domain padding + masking via `DomainAwareLinear` projectors.
3. **Per-robot conventions are declarative.** Each adapter exposes:
   - `default_gripper_convention()` — `(closed_at, open_at)` in native units, used to map action gripper to `[0,1]`.
   - `proprio_layout()` — declares which parquet columns concatenate to form `observation.state` and where the gripper lives.
   At recording-session start, both get written into `info.json` so the exporter has a self-contained source of truth.
4. **Stats files**: exporter writes:
   - `meta/action_stats.json` — q99-derived pseudo-`mean`/`std` (`mean = (q01+q99)/2`, `std = (q99-q01)/2`), length 7, with `"convention": "q99_derived_midpoint_halfrange"` metadata field. Compatible with the existing decoder's `physical = mean + arr * std` formula when the trainer outputs q99-normalized actions.
   - `meta/action_stats_q99.json` — `q01` / `q99` / `mask`, length 7. For X-VLA-Adapter trainer.
   - `meta/proprio_stats_q99.json` — `q01` / `q99` / `mask`, length = per-robot proprio dim. For X-VLA-Adapter trainer (`load_q99_proprio_stats` consumes it).
5. **Existing 240 episodes** with `info.json` `robot_type=unknown` are exportable via explicit CLI override; the exporter never silently picks a default.
6. **Last frame is dropped.** Each episode of `n` parquet rows produces `n-1` exported rows (one per valid `obs[t]→obs[t+1]` delta). Removes the chicken-and-egg of "verify the loader doesn't repeat the zero-pad" against a loader that does not yet exist. **Loader responsibility**: handling exported episodes shorter than the loader's `action_chunk_len` (e.g. an `n=8` input → `out_n=7` cannot form a single complete length-8 chunk) is delegated to the X-VLA-side loader follow-up, which must either pad, drop short episodes, or enforce `n_input >= action_chunk_len + 1` upstream.

## Non-goals (explicit follow-ups, ALL load-bearing for "actually shipping a working VLA")

- **Inference contract YAML update** (`gemma_libero_v1.yaml`): switch `action.normalization.method` to either `mean_std` or `minmax_neg1_pos1` (mathematically equivalent here — both apply `physical = mean + arr * std`) and verify the operator-facing docs reflect the q99-derived semantic of `mean`/`std`. Without this verification, an operator may interpret the file as actual mean/std (which it is not) and miscalibrate downstream tooling.
- **`MIMICREC_VLA_DEST_ROOT` default** in `contract.py:166` currently points at `~/vla-gemma-4/data/local`; should target X-VLA-Adapter's `data/local/`.
- **X-VLA-Adapter side dataset config**: a new `configs/data/lerobot_so101.yaml` plus a new dataset loader that converts our exported parquets into the X-VLA `Batch` schema (`src/vla_project/data/schema.py`). The existing `lerobot_libero_dataset.py` is LIBERO-specific and won't accept our format. Proprio q99 stats need wrapping into the X-VLA `data/norm_stats/<dataset>.json` per-dataset-key format. **This is non-trivial coordination work**, not just a config tweak.
- **`SO101Adapter.read_state` proprio bug**: today it leaves `RobotState.gripper_pos = 0.0` (the gripper value lives in `joint_pos[5]`). Inference proprio therefore differs in semantics from training proprio in ways that even per-domain projectors only partially mask. Should be fixed before serious eval on real hardware.
- **`learn data bottle/` action.joint_pos anomaly**: hand-teach reBot episodes have static `bundle.action.q` because the operator physically moves the arm in gravity-comp mode. obs→obs deltas are fine to train on, but the dataset should be tagged so consumers know.

## Background

### Empirical comparison of three delta definitions on real episodes

Measured per-step pairwise `|ΔT_a − ΔT_b|` on 8 sample episodes (script ad hoc; not committed).

| Source dataset | obs→obs | act→act | obs→act | obs→obs vs obs→act, p99 |
|---|---|---|---|---|
| `datasets/SO101/` (33 eps, normal teleop) | mean ~5 mm / 22 mrad | mean ~6 mm / 25 mrad | mean ~21 mm / 91 mrad | **60 mm position, 270 mrad rotation** |
| `datasets/learn data bottle/` (200+ eps, hand-teach on reBot) | mean ~3-5 mm / 8-10 mrad | **~0.1 mm / 0.5 mrad** (static command) | ~400 mm / 2 rad (junk by extension) | n/a |

Findings:

- For normal teleop (SO-101), obs→obs and act→act agree within ~3 mm / 14 mrad. They differ from obs→act by tens of mm — the ~1-tick tracking lag between commanded and observed joints, which Codex flagged as a real concern.
- For hand-teach (reBot), only **obs→obs** captures actual motion — `action.joint_pos` is the held command, near-static.
- Choosing **obs→obs** is the only definition that works across both teleop and hand-teach data.

### Inference decoder semantics (informs the choice)

`backend/mimicrec/inference/action_decoder.py` initializes `T_curr = fk.matrix(observed_q)` at chunk start and chains `T_next = T_curr @ T_delta` step-by-step within the chunk. T_curr is **not** re-synced to obs mid-chunk; the next chunk's `decode()` re-initializes from the new observed state. obs→obs training matches this semantic: each delta is "what the robot actually did" between two observed poses, and the chain accumulates one chunk's worth of predicted future obs poses.

### Robot DOF and joint_pos semantics (verified against parquet data)

| Robot | `joint_pos` shape | Meaning | `gripper_pos` semantic |
|---|---|---|---|
| SO-101 | `[6]` | 5 arm joints + 1 packed gripper at `joint_pos[5]` (degrees) | Same value as `joint_pos[5]` (duplicated). raw `[0, 100]`, 0=closed |
| reBot  | `[6]` | 6 arm joints (radians, hardware-measured) | Independent normalized open-close command in `[0, 1]`, 1=closed / 0=open per `configs/mapper/so_to_rebotarm_ee.yaml` (controller input, not a hardware angle) |

So the natural per-robot proprio composition is:
- SO-101: `joint_pos` alone (6-dim) — gripper info already in slot 5
- reBot: `joint_pos` ∥ `gripper_pos` (7-dim) — gripper is independent

### X-VLA-Adapter architecture (informs design alignment)

From `X-VLA-Adapter/docs/architectures/x_vla_adapter.md`:

- Model action shape is `[B, H_act=8, A=7]` produced by a **domain-aware** Action Decoder (`DomainAwareLinear`).
- Proprio dim `D_prop=8` is the LIBERO default; multi-domain training pads per-domain proprio to a common dim with masking.
- All projectors (proprio, last-action, scene, wrist) are `DomainAware`, routed by `domain_id`. Adding SO-101 / reBot is a matter of registering them as new domains with their own `D_prop` (handled X-VLA side, follow-up).

So our exporter does **not** need to force a uniform proprio shape across robots; X-VLA-Adapter's per-domain routing handles that.

(Note: `lerobot_libero_dataset.py:action_format ∈ {"native","ee6d"}` is a parameter inside the LIBERO-specific loader, not a system-wide mode. We will need a NEW SO-101 / reBot dataset loader on the X-VLA side; that's the follow-up.)

## Design

### §1. Architecture overview

```
[recording time]
  Adapter (SO101 / reBot / ...)
    ├── existing: bundle.action.q, bundle.state.{joint_pos, gripper_pos, ee_pos, ee_rotvec}
    └── NEW classmethods on the adapter:
            default_gripper_convention() -> GripperConvention(closed_at, open_at)
            proprio_layout() -> ProprioLayout(columns, output_names, gripper_via_column,
                                              gripper_index_in_column)
         ↓
  recording-session bootstrap
    └── NEW: info.json gets robot_type / gripper_convention / proprio_layout
         ↓
  writer/parquet_row.py — UNCHANGED. observation.state.ee_pos/ee_rotvec already populated by daemon FK.

[export time]
  vla_compat.convert_episode_table(table, instruction_text, gripper_convention, proprio_layout)
    ├── action[t,:6] = matrix-compose ee_local delta from obs.ee_pos/rotvec[t→t+1]
    │                  for t in [0, n-2]                          ← n-1 rows, no zero-pad
    ├── action[:,6]  = clip((raw_gripper - closed_at) / (open_at - closed_at), 0, 1)
    │                  for t in [0, n-2]                          ← matches action shape
    └── observation.state[t,:] = per-robot column concat per proprio_layout, verbatim
                                  for t in [0, n-2]
         ↓
  exporter/info_json.py
    └── features.action.names           = [ee_dx, ee_dy, ee_dz, ee_drx, ee_dry, ee_drz, gripper]
        features.observation.state.shape = [n_proprio]   ← derived from converted table list size
        features.observation.state.names = proprio_layout-derived
        top-level robot_type / gripper_convention / proprio_layout copied through
         ↓
  exporter/stats.py
    ├── action_stats.json      (pseudo mean/std from q01/q99, length 7)  ← inference decoder
    ├── action_stats_q99.json  (q01/q99/mask, length 7)                  ← X-VLA trainer
    └── proprio_stats_q99.json (q01/q99/mask, length = D_prop_robot)     ← X-VLA trainer
         ↓
  orchestrator
    └── reads gripper_convention + proprio_layout from input info.json,
        fails loudly if missing or robot_type=unknown without a CLI override.
        Derives n_proprio from the FIRST converted episode, asserts all
        subsequent episodes match (raise ValueError on mismatch — NOT
        Python `assert`, which `-O` strips).
```

Recording schema (parquet columns), `ActionDecoder`, `ContractSpec`, and the contract YAML are not modified by this work.

### §2. Adapter API additions

New module `backend/mimicrec/adapters/types.py`:

```python
@dataclass(frozen=True)
class GripperConvention:
    closed_at: float    # native-unit value when fully closed
    open_at:   float    # native-unit value when fully open

    def __post_init__(self):
        if abs(self.open_at - self.closed_at) < 1e-9:
            raise ValueError(f"GripperConvention has zero span: {self}")
    # Forward map: action_gripper = clip((raw - closed_at) / (open_at - closed_at), 0, 1)
    # Works for both closed_at < open_at (SO-101) and closed_at > open_at (reBot).


@dataclass(frozen=True)
class ProprioLayout:
    """Declarative composition for observation.state at export time.

    `columns` is the ordered tuple of parquet column names whose values are
    concatenated row-by-row to form observation.state. List columns
    (e.g. joint_pos: list<float>[6]) and scalar columns (gripper_pos: float)
    are both supported.

    `output_names` is the full list of names for the resulting observation.state
    vector, in concat order, with one name per output dim (including gripper if
    present). `to_vla_info` uses this list verbatim — no special-casing of
    where the gripper lives. Length agreement with the actual concat dim is
    validated at runtime in `_build_observation_state` (cannot be checked here
    because dim depends on parquet list-column widths).

    `gripper_via_column` names which entry in `columns` carries the gripper
    value used by the action label. `gripper_index_in_column` is the offset
    within that column; for SO-101 the gripper is at joint_pos[5] (offset 5
    within the joint_pos list). For reBot it is the only entry of the scalar
    gripper_pos column (offset 0).

    `__post_init__` validates only structural relationships among fields
    (no table data needed): membership of gripper_via_column in columns, and
    a non-negative gripper index.
    """
    columns: tuple[str, ...]
    output_names: tuple[str, ...]
    gripper_via_column: str
    gripper_index_in_column: int

    def __post_init__(self):
        if self.gripper_via_column not in self.columns:
            raise ValueError(
                f"gripper_via_column {self.gripper_via_column!r} not in columns {self.columns}"
            )
        if self.gripper_index_in_column < 0:
            raise ValueError(
                f"gripper_index_in_column must be >= 0, got {self.gripper_index_in_column}"
            )
```

Each adapter declares both via classmethods:

```python
class SO101Adapter:
    @classmethod
    def default_gripper_convention(cls) -> GripperConvention:
        return GripperConvention(closed_at=0.0, open_at=100.0)
        # SO-101 RANGE_0_100: 0=closed, 100=open

    @classmethod
    def proprio_layout(cls) -> ProprioLayout:
        return ProprioLayout(
            columns=("observation.state.joint_pos",),
            output_names=("shoulder_pan","shoulder_lift","elbow_flex",
                          "wrist_flex","wrist_roll","gripper"),
            gripper_via_column="observation.state.joint_pos",
            gripper_index_in_column=5,   # packed gripper at joint_pos[5]
        )

class ReBotZmqAdapter:
    @classmethod
    def default_gripper_convention(cls) -> GripperConvention:
        return GripperConvention(closed_at=1.0, open_at=0.0)
        # Derived from configs/mapper/so_to_rebotarm_ee.yaml.
        # NOTE: a default inferred from the SO→reBot mapper config, not a
        # measured hardware contract. Future per-session calibration override
        # would replace this at recording time.

    @classmethod
    def proprio_layout(cls) -> ProprioLayout:
        return ProprioLayout(
            columns=("observation.state.joint_pos", "observation.state.gripper_pos"),
            # NOTE: `join3` (no `t`) intentional — reBotArm URDF spells joint3
            # as `join3` upstream (tracked in configs/mapper/so_to_rebotarm_ee.yaml:12).
            output_names=("joint1","joint2","join3","joint4","joint5","joint6","gripper"),
            gripper_via_column="observation.state.gripper_pos",
            gripper_index_in_column=0,   # scalar column, only entry
        )

class MockRobotAdapter:
    # Does NOT implement default_gripper_convention or proprio_layout.
    # Datasets recorded with mock adapters have no gripper_convention block in
    # info.json; the exporter then fails loudly without a CLI override.
    pass
```

### §3. Recording-session bootstrap

Today `backend/mimicrec/recording/dataset_layout.py:76` writes `robot_type: "unknown"`. Update the writer site so that at recording-session start, with the active adapter in hand:

```python
info["robot_type"] = adapter.__class__.__name__   # e.g. "SO101Adapter", "ReBotZmqAdapter"
if hasattr(adapter, "default_gripper_convention"):
    conv = adapter.default_gripper_convention()
    info["gripper_convention"] = {"closed_at": conv.closed_at, "open_at": conv.open_at}
if hasattr(adapter, "proprio_layout"):
    layout = adapter.proprio_layout()
    info["proprio_layout"] = {
        "columns": list(layout.columns),
        "output_names": list(layout.output_names),
        "gripper_via_column": layout.gripper_via_column,
        "gripper_index_in_column": layout.gripper_index_in_column,
    }
```

Mock / sim adapters that don't implement these methods leave the fields out, and the exporter rejects the dataset unless given an explicit CLI override.

Future calibration override (out of scope): a session config block `gripper_convention: {...}` would replace the adapter default at this site.

### §4. Exporter logic (`vla_compat.py`)

```python
import numpy as np
import pyarrow as pa
from scipy.spatial.transform import Rotation as R

# Sanity bound: real teleop / hand-teach per-step rotation deltas at 15-30 fps
# stay well below this. Hitting it indicates either bad input data or a frame
# mismatch — fail loudly rather than emitting an axis-discontinuity sample.
_ROT_DELTA_SANITY_RAD = 1.0   # ~57 deg

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
                    f"for gripper_index_in_column={idx} (len={None if row is None else len(row)})"
                )
            out[r] = row[idx]
        return out
    if layout.gripper_index_in_column != 0:
        raise ValueError(
            f"scalar column {layout.gripper_via_column} cannot have gripper_index_in_column != 0"
        )
    return np.asarray(col.to_pylist(), dtype=np.float64)

def _build_observation_state(table: pa.Table, layout: ProprioLayout) -> np.ndarray:
    """Concatenate the adapter-declared columns row-by-row, verbatim.

    Validates at runtime: every layout column exists in the table, list
    columns have consistent (non-ragged) widths, and the concatenated dim
    matches len(layout.output_names). Raises ValueError on any mismatch
    (NOT IndexError / ArrowInvalid leakage).
    """
    cols = []
    for name in layout.columns:
        if name not in table.column_names:
            raise ValueError(
                f"layout column {name!r} not in parquet (have: {sorted(table.column_names)})"
            )
        col = table.column(name)
        if pa.types.is_list(col.type) or pa.types.is_fixed_size_list(col.type):
            rows = col.to_pylist()
            if any(r is None for r in rows):
                raise ValueError(f"null row in list column {name}")
            widths = {len(r) for r in rows}
            if len(widths) != 1:
                raise ValueError(f"ragged widths in list column {name}: {sorted(widths)}")
            cols.append(np.asarray(rows, dtype=np.float32))   # [n, k]
        else:
            cols.append(np.asarray(col.to_pylist(), dtype=np.float32)[:, None])  # [n, 1]
    out = np.concatenate(cols, axis=1)   # [n, sum(k_i)]
    if out.shape[1] != len(layout.output_names):
        raise ValueError(
            f"concatenated proprio dim {out.shape[1]} != len(output_names) "
            f"{len(layout.output_names)} for layout columns={layout.columns}"
        )
    return out

def convert_episode_table(
    *, table: pa.Table, instruction_text: str,
    gripper_convention: GripperConvention,
    proprio_layout: ProprioLayout,
) -> ConvertedEpisode:
    n = table.num_rows
    if n < 2:
        raise ValueError(f"episode too short for delta computation: n={n}")
    out_n = n - 1   # last frame dropped; one valid delta per consecutive obs pair

    # ---- Action: ee_delta(6) + gripper(1) in [0,1] ----
    ee_pos = np.asarray(table.column("observation.state.ee_pos").to_pylist(),    dtype=np.float64)  # [n,3] m
    ee_rot = np.asarray(table.column("observation.state.ee_rotvec").to_pylist(), dtype=np.float64)  # [n,3] axis-angle rad
    if not (np.isfinite(ee_pos).all() and np.isfinite(ee_rot).all()):
        raise ValueError("non-finite values in observation.state.ee_pos/ee_rotvec")
    actions = np.zeros((out_n, 7), dtype=np.float32)
    for t in range(out_n):
        T_curr = _to_T(ee_pos[t],   ee_rot[t])
        T_next = _to_T(ee_pos[t+1], ee_rot[t+1])
        T_delta = np.linalg.inv(T_curr) @ T_next                        # ee_local frame
        actions[t, 0:3] = T_delta[:3, 3]
        rotvec = R.from_matrix(T_delta[:3, :3]).as_rotvec()             # principal axis-angle
        if np.linalg.norm(rotvec) > _ROT_DELTA_SANITY_RAD:
            raise ValueError(
                f"per-step rotation delta {np.linalg.norm(rotvec):.3f} rad at t={t} "
                f"exceeds {_ROT_DELTA_SANITY_RAD} rad sanity bound — likely frame mismatch "
                f"or bad input data, not real motion"
            )
        actions[t, 3:6] = rotvec

    raw_gripper = _resolve_raw_gripper_column(table, proprio_layout)    # [n]
    if not np.isfinite(raw_gripper).all():
        raise ValueError("non-finite values in gripper column")
    actions[:, 6] = _normalize_unit(raw_gripper[:out_n], gripper_convention)

    # ---- observation.state: per-adapter column concat, verbatim, first n-1 rows ----
    obs_state_full = _build_observation_state(table, proprio_layout).astype(np.float32)
    if not np.isfinite(obs_state_full).all():
        raise ValueError("non-finite values in observation.state columns")
    obs_state = obs_state_full[:out_n]

    arrays = {
        "action":              pa.array(actions.tolist(),
                                        type=pa.list_(pa.float32(), 7)),
        "observation.state":   pa.array(obs_state.tolist(),
                                        type=pa.list_(pa.float32(), obs_state.shape[1])),
        "language_instruction": pa.array([instruction_text] * out_n, type=pa.string()),
    }
    # Passthrough columns (timestamp / index / video_frame_index) sliced to first out_n rows.
    for col in _PASSTHROUGH_COLUMNS:
        if col in table.column_names:
            arrays[col] = table.column(col).slice(0, out_n)
    return ConvertedEpisode(table=pa.table(arrays))
```

**Why drop last frame, not zero-pad.** A previous draft zero-padded `actions[n-1, :6] = 0`. Verification that a downstream loader does not repeat the terminal row when sampling chunks past `n-1` requires a loader that does not yet exist (X-VLA-side dataset config is a follow-up). Dropping the last row removes that chicken-and-egg: the export contains exactly one valid `obs[t]→obs[t+1]` delta per row, and chunk samplers can use uniform "advance one row at a time" semantics regardless of episode end. Per-episode data loss is `1/n` rows — about `0.2%` for a typical 500-frame episode, but up to `50%` for an `n=2` clip and meaningfully significant for episodes shorter than ~50 frames. Loaders that need full chunks must filter `out_n < action_chunk_len` episodes upstream.

**Why matrix compose, not rotvec subtraction.** Rotvec subtraction is unstable near π and around antipodal axis flips. Composing 4×4 transforms then extracting via `Rotation.from_matrix(...).as_rotvec()` returns the principal axis-angle (always shortest path), well-defined except exactly at ±π. Real per-step deltas in our data stay below 0.1 rad (verified empirically); the runtime sanity check at 1.0 rad fails fast on bad input.

### §5. info.json features (`info_json.py`)

```python
ACTION_NAMES = ["ee_dx", "ee_dy", "ee_dz", "ee_drx", "ee_dry", "ee_drz", "gripper"]

def to_vla_info(info, *, robot_type, gripper_convention, proprio_layout, n_proprio):
    new = copy.deepcopy(info)
    new["robot_type"] = robot_type
    new["gripper_convention"] = gripper_convention
    new["proprio_layout"] = {
        "columns": list(proprio_layout.columns),
        "output_names": list(proprio_layout.output_names),
        "gripper_via_column": proprio_layout.gripper_via_column,
        "gripper_index_in_column": proprio_layout.gripper_index_in_column,
    }
    features = new.setdefault("features", {})

    # Replace action wholesale — joint-name reuse from the current code is a latent bug.
    features["action"] = {"dtype": "float32", "shape": [7], "names": ACTION_NAMES}

    # observation.state names come straight from the layout — no per-robot
    # special-casing. The adapter is responsible for declaring output_names
    # in concat order with one entry per output dim. _build_observation_state
    # validates the actual concat dim against len(output_names) at runtime.
    obs_names = list(proprio_layout.output_names)
    if len(obs_names) != n_proprio:
        raise ValueError(
            f"proprio name/shape mismatch: layout.output_names has {len(obs_names)} entries "
            f"but n_proprio={n_proprio}"
        )
    features["observation.state"] = {
        "dtype": "float32",
        "shape": [n_proprio],
        "names": obs_names,
    }

    features["language_instruction"] = {"dtype": "string", "shape": [1], "names": None}
    return new
```

### §6. Stats: triple output (`stats.py` and orchestrator)

```python
_ACTION_STATS_CONVENTION = "q99_derived_midpoint_halfrange"

def compute_stats(
    tables: Iterable[pa.Table],
) -> tuple[dict, dict, dict]:
    """Return (action_stats, action_q99, proprio_q99).

    action_stats has `mean`, `std`, AND a `convention` metadata field. The
    mean/std are NOT the actual mean/std of the action distribution; they are
    derived from q01/q99 so that the existing decoder's `physical = mean +
    arr * std` formula correctly denormalizes a model output `arr` in [-1,+1]
    that came from a q99-normalized training pipeline. Documented for
    operators in the inference contract README follow-up.
    """
    action_rows, proprio_rows = [], []
    for t in tables:
        action_rows.extend(t.column("action").to_pylist())
        proprio_rows.extend(t.column("observation.state").to_pylist())
    if not action_rows:
        raise ValueError("compute_stats: no rows")

    arr_a = np.asarray(action_rows, dtype=np.float64)    # [N, 7]
    arr_p = np.asarray(proprio_rows, dtype=np.float64)   # [N, D_prop_robot]

    # action q01/q99/mask (length 7) — for X-VLA trainer
    a_q01 = np.quantile(arr_a, 0.01, axis=0)
    a_q99 = np.quantile(arr_a, 0.99, axis=0)
    a_mask = [True] * 7

    # action pseudo mean/std (length 7) — derived from q01/q99 for the
    # inference contract decoder. NOT the actual mean/std of arr_a.
    a_midpoint   = (a_q99 + a_q01) / 2.0
    a_half_range = np.maximum((a_q99 - a_q01) / 2.0, 1e-6)

    # proprio q01/q99/mask (length = D_prop_robot) — for X-VLA trainer
    p_q01 = np.quantile(arr_p, 0.01, axis=0)
    p_q99 = np.quantile(arr_p, 0.99, axis=0)
    p_mask = [True] * arr_p.shape[1]

    return (
        {
            "mean": a_midpoint.tolist(),
            "std":  a_half_range.tolist(),
            "convention": _ACTION_STATS_CONVENTION,
        },
        {"q01": a_q01.tolist(), "q99": a_q99.tolist(), "mask": a_mask},
        {"q01": p_q01.tolist(), "q99": p_q99.tolist(), "mask": p_mask},
    )
```

The orchestrator writes:
- `meta/action_stats.json`        ← `a_pseudo_mean_std`
- `meta/action_stats_q99.json`    ← `a_q99`
- `meta/proprio_stats_q99.json`   ← `p_q99`

Wrapping these into the X-VLA-Adapter `dataset_statistics.json` per-dataset-key format is an out-of-scope manual step until the X-VLA-side dataset config follow-up lands. The wrapper shape is trivial:

```json
{ "<dataset_name>": { "action": <action_stats_q99.json contents>,
                      "proprio": <proprio_stats_q99.json contents> } }
```

### §7. Orchestrator and CLI override

`backend/mimicrec/datasets/exporters/orchestrator.py:_export_vla_compat`:

1. Read input `info.json` early. Resolve `robot_type`, `gripper_convention`, `proprio_layout`.
2. If any of the three is missing or `robot_type == "unknown"`:
   - If a CLI / API override was supplied, use it.
   - Else raise `ValueError` with remediation: 'dataset\'s info.json declares `robot_type=unknown`. Re-record after the recording-layer change in this PR, or pass `--robot-type so101` (or `--robot-type rebot`) to override for one-off reprocessing of pre-existing data.'
3. Pass the resolved `GripperConvention` and `ProprioLayout` into `convert_episode_table` for every episode.
4. After conversion, derive `n_proprio` from the first converted episode's `observation.state` fixed-list size. Iterate the rest and `raise ValueError` (NOT `assert`) if any episode's size disagrees — guards against per-episode adapter swaps that should never happen.
5. Call `compute_stats(...)` and write all three stats files.
6. Pass `robot_type` / `gripper_convention` / `proprio_layout` / `n_proprio` to `to_vla_info(...)` so the output `info.json` carries them through with the correct `observation.state.shape`.

Expose the override at the API surface (`api/routes/datasets.py`) and CLI as optional parameters; default behavior is fail-loud.

For pre-existing 240 episodes, exporting with `--robot-type so101` / `--robot-type rebot` reconstructs the convention/layout from the registered adapter class.

### §8. Backwards compatibility

- **Existing recorded parquet files**: usable as-is. All 240 episodes carry `observation.state.{joint_pos, gripper_pos, ee_pos, ee_rotvec}`. No migration of recorded data needed.
- **Existing dataset `info.json` with `robot_type=unknown`**: see §7 — explicit override required. Document this in `configs/inference/README.md`.
- **Existing exported VLA-compat datasets**: action and proprio formats both change, episode lengths shrink by 1 row. Re-export required (operator decision when to delete old exports). Exporter does not touch already-exported data.
- **`learn data bottle/` (hand-teach reBot data)**: `action.joint_pos` is static (gravity-comp mode); obs→obs deltas are still valid for training. No special handling — choose obs→obs (this design).

## Validation

### Unit tests (replacing `tests/unit/test_exporter_vla_compat.py`)

- `test_action_is_ee_delta_with_gripper_in_unit_range`
- `test_action_uses_ee_local_frame_via_matrix_compose` — non-identity orientation; assert `T_curr @ T_delta` reconstructs `T_next` (translation 1e-6, rotation 1e-6 rad). Reconstruction-based, not component-similarity-based.
- `test_rotation_delta_near_pi_almost_one_rad_passes_reconstruction` — `T_curr` and `T_next` whose relative rotation is ~0.9 rad; assert reconstruction succeeds.
- `test_rotation_delta_above_one_rad_raises_sanity` — relative rotation 1.1 rad triggers the `_ROT_DELTA_SANITY_RAD` guard.
- `test_rotation_delta_near_zero_returns_small_axisangle`
- `test_export_drops_last_frame_episode_n_to_n_minus_1` — input has n rows, output has n-1.
- `test_episode_n_equals_2_outputs_one_row` — minimal valid case.
- `test_episode_n_equals_1_raises`
- `test_gripper_normalized_so101_convention` — (closed=0, open=100) → 0 → 0, 100 → 1.
- `test_gripper_normalized_rebot_inverted_convention` — (closed=1, open=0) → 1 → 0, 0 → 1.
- `test_gripper_clipped_when_raw_overshoots`
- `test_gripper_convention_zero_span_rejected_at_construction` — `GripperConvention.__post_init__` raises.
- `test_proprio_layout_validation_gripper_via_column_in_columns` — `ProprioLayout.__post_init__` raises.
- `test_proprio_layout_validation_gripper_index_negative_raises`
- `test_observation_state_so101_is_joint_pos_verbatim` — shape [6], values match input parquet `observation.state.joint_pos` row-for-row (sliced to n-1).
- `test_observation_state_rebot_concatenates_joint_pos_and_gripper_pos` — shape [7], last col equals `observation.state.gripper_pos`.
- `test_observation_state_missing_layout_column_raises_value_error` — not IndexError / ArrowInvalid.
- `test_observation_state_ragged_list_column_raises_value_error`
- `test_observation_state_dim_mismatch_with_output_names_raises_value_error`
- `test_resolve_gripper_index_out_of_bounds_raises_value_error`
- `test_resolve_gripper_scalar_column_with_nonzero_index_raises_value_error`
- `test_non_finite_inputs_raise` — NaN/Inf in any input column.
- `test_short_episode_n_equals_action_chunk_len_exports_one_less_row` — confirms `n=8 → out_n=7` boundary; loader handling is its responsibility (covered by integration test note).
- `test_info_json_action_names_are_ee_delta_components`
- `test_info_json_observation_state_shape_matches_parquet_list_width`
- `test_info_json_carries_robot_type_gripper_convention_proprio_layout`
- `test_info_json_raises_on_name_count_vs_n_proprio_mismatch`
- `test_compute_stats_returns_action_pseudo_mean_std_action_q99_proprio_q99`
- `test_action_stats_mean_equals_midpoint_of_action_q99` — `mean == (q01 + q99) / 2` by construction.
- `test_action_stats_std_equals_half_range_of_action_q99`
- `test_action_stats_carries_convention_field`
- `test_action_q99_mask_all_true_for_seven_dim_action`
- `test_proprio_q99_length_matches_per_robot_dim`

`tests/unit/test_recording_info_json.py` (new):
- `test_session_start_writes_robot_type_gripper_convention_proprio_layout_for_so101`
- `test_session_start_writes_them_for_rebot`
- `test_session_start_omits_optional_fields_for_mock_adapter`

`tests/unit/test_exporter_orchestrator.py` (extend):
- `test_orchestrator_fails_when_robot_type_unknown_and_no_override`
- `test_orchestrator_uses_cli_override_when_provided`
- `test_orchestrator_raises_when_episodes_have_inconsistent_proprio_dim`

### Integration test (`tests/integration/test_vla_compat_roundtrip.py`)

- End-to-end: build a tiny synthetic dataset (both SO-101-like and reBot-like fixtures) with non-trivial obs trajectory, export, then verify:
  - Output `action` column is shape [7]
  - First few rows of `action[:, :6]` reconstruct the next obs poses when chained from the first obs pose (round-trip test)
  - Output `observation.state` shape matches the per-adapter expected dim (6 for SO-101, 7 for reBot)
  - All three stats files present, lengths match expected dims
  - Output `info.json` has `robot_type`, `gripper_convention`, `proprio_layout`, and correct `features.observation.state.shape`
  - Output episode is `n_input - 1` rows long
  - **Short-episode boundary**: also fixture an `n_input = 8` episode (matching X-VLA's `action_chunk_len=8`); export succeeds with `out_n=7` and the spec-documented loader requirement is documented in the test docstring as the consumer's responsibility.

### Pre-merge checks (manual, document in PR description)

- Re-export both real datasets (`SO101/`, `learn data bottle/`) with `--robot-type so101` / `--robot-type rebot` overrides.
- Spot-check action stats: position dims q01/q99 in single-digit cm range; rotation dims under ~0.5 rad; gripper q01/q99 close to 0 / 1.
- **reBot calibration empirical check**: after `--robot-type rebot` re-export, verify `action_stats_q99.json`'s gripper dim has `q01 ≈ 0` and `q99 ≈ 1`. If not, the inferred reBot `(closed_at=1, open_at=0)` does not match the recorded distribution and the convention needs measurement, not inference.
- Spot-check proprio stats: SO-101 q01/q99 widths broadly match each joint's typical operating range; reBot last dim (gripper_pos) lies within `[0, 1]` — note this is the **normalized open-close command** the gripper position controller receives (per `configs/mapper/so_to_rebotarm_ee.yaml`), NOT a hardware-measured angle in radians.
- (Once X-VLA-side dataset config follow-up lands) Smoke-load the exported dataset via the new SO-101 loader; verify proprio shape, action shape, stats wiring all line up.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Operator misinterprets `action_stats.json`'s `mean`/`std` as actual statistics | `convention: "q99_derived_midpoint_halfrange"` field in the file, top-of-spec warning, contract YAML follow-up to update operator-facing docs. |
| Trained model emits q99-normalized actions but a misconfigured contract decoder denorms with a different formula | Both stats files written; contract YAML follow-up confirms the decoder's `physical = mean + arr * std` matches our pseudo mean/std semantic. |
| `learn data bottle/` action.joint_pos anomaly (hand-teach) | obs→obs is robust to it. Documented as known. |
| obs→obs vs obs→act diverge by ~60 mm (p99) for SO-101 normal teleop | Accepted: model trained on obs→obs predicts realized trajectory; decoder chains obs→obs deltas; distributions match. |
| reBot gripper convention `(1.0, 0.0)` derived from one mapper YAML rather than measured hardware | Empirical pre-merge check on reBot stats. Future per-session calibration override is the proper fix; out of scope. |
| X-VLA-Adapter side has no SO-101/reBot dataset loader yet | Explicit follow-up. This PR delivers data + stats; coordinated work required to actually train. |
| Per-domain projector handles per-robot proprio dim, but `SO101Adapter.read_state`'s runtime proprio (with `gripper_pos=0.0` placeholder bug) still differs in semantics from training proprio | Documented as separate follow-up. X-VLA's per-domain projector partially absorbs the difference, but the bug should be fixed before serious eval. |
| Per-step rotation delta exceeds 1 rad at export time (would indicate frame mismatch or bad input data) | Runtime `_ROT_DELTA_SANITY_RAD` guard raises. |
| Episodes shorter than the future loader's `action_chunk_len` cannot form a single complete chunk after the n→n-1 drop | Loader-side responsibility (filter, pad, or enforce minimum). Integration test documents the boundary; spec calls it out in Goals item 6. |

## Open questions (none blocking)

None. All design decisions confirmed in brainstorming with the user; remaining items are explicit follow-ups (above) and manual verifications listed in "Pre-merge checks".
