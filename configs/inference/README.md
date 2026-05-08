# Inference Contracts

YAML files in this directory describe how MimicRec talks to a Vision-Language-Action (VLA) HTTP server. One file per server / model variant. The schema is enforced by `mimicrec.inference.contract.ContractSpec` (pydantic v2). Validation runs at session start; bad files fail fast with a 400.

See spec `docs/superpowers/specs/2026-05-05-vla-inference-interface-design.md` §6 for the full reference.

## Top-level blocks

| Block | Purpose |
|---|---|
| `name` / `description` | `name` is a human-readable display title shown in the UI dropdown alongside the file stem. The **file stem** (not `name`) is what `GET /api/configs/inference/<id>` and the start endpoint use as the identifier — pick a file name that's URL-safe and unique. `description` is shown as inline help text in the dropdown. |
| `endpoint` | URL, method, timeout, headers, retry policy. |
| `request` | How MimicRec packs the HTTP body — images, proprioceptive state, instruction. |
| `response` | How MimicRec parses the response — chunk shape, action format, optional `done` signal. |
| `loop` | Producer tuning — half-prefetch threshold, max inflight requests. |

## `endpoint`

```yaml
endpoint:
  url: "http://localhost:8001/predict"
  method: POST                           # only POST is implemented in MVP
  timeout_s: 5.0
  headers:
    Authorization: "Bearer ${VLA_API_TOKEN}"   # ${ENV} interpolation
  retry:
    max_attempts: 0                      # see warning below
```

`${VAR}` placeholders in any string value are substituted from the environment at load time. Missing env var → 400. Retry is intentionally 0 for MVP — increasing it amplifies state drift and slow-stop already handles transient errors.

## `request.images`

Map MimicRec camera names (configured by your session) to the JSON field names the server expects. Each entry:

```yaml
front:
  field: image_primary           # JSON field on the request body
  encoding: jpeg_base64          # only encoding implemented in MVP
  resize: [224, 224]             # H, W. Resize is bilinear (PIL).
  jpeg_quality: 90               # 1..95 typical
```

Encoding is BGR→RGB internally before JPEG (cameras emit BGR per `Frame.image`).

## `request.state`

```yaml
state:
  field: proprio                 # JSON field on request
  components: [joint_pos, gripper_pos]
  normalization:
    method: none                 # none | minmax_neg1_pos1 | mean_std (MVP: none recommended)
```

`components` is concatenated into a single flat vector, in the order listed. Available keys:
- `joint_pos` — `RobotState.joint_pos` (degrees), length = robot arm DOF
- `gripper_pos` — scalar, normalized [-1, +1]

(Other components like `joint_vel` are reserved for future expansion.)

## `request.instruction`

```yaml
instruction:
  field: instruction             # JSON field name; the value is provided at session start (not in the YAML)
```

The string is settable via `PUT /api/session/inference/instruction` during READY.

## `request.extra_fields`

Static key-values added to every request. Useful for `model_version` markers etc.

## `response.actions_path`

JSONPath into the response body where the action chunk lives. For a body like `{"actions": [[...], [...], ...]}`, set `actions_path: actions`. Nested paths use dots (`response.predictions.chunk`).

## `response.chunk`

```yaml
chunk:
  expected_size: 16              # nominal chunk length
  on_size_mismatch: use_actual   # use_actual (continue with whatever came) | reject (raise)
```

## `response.action`

The most consequential block. Defines how MimicRec interprets each per-step row of the chunk.

```yaml
action:
  type: ee_delta                 # MVP: ee_delta only (joint_position / ee_pose deferred)
  frame: ee_local                # ee_local | world. Model conventions vary.
  pose:
    units: meter_axisangle_rad   # MVP: only this is implemented
  gripper:
    kind: absolute               # absolute | delta | binary
    units: normalized_0_1        # for absolute/delta: literal values; for binary: threshold at 0.5
  components: [ee_delta, gripper]            # order in the per-step vector. ee_delta=6, gripper=1, total=7
  normalization:
    method: mean_std             # none | minmax_neg1_pos1 | mean_std
    stats_ref:
      type: vla_export           # vla_export | absolute
      dataset: SO101             # → ${MIMICREC_VLA_DEST_ROOT}/SO101/meta/action_stats.json
      # path: /abs/path/action_stats.json   # used when type=absolute
```

**Stats convention** (used by both `mean_std` and `minmax_neg1_pos1`):

```
physical = mean + arr * std
```

For `mean_std`: stats hold population mean/std (typical).
For `minmax_neg1_pos1`: stats encode midpoint (`mean`) and half-range (`std`), so `arr ∈ [-1, +1]` maps to `[mean-std, mean+std]`. Verify your stats producer agrees with this convention.

If your server already emits physical units (meters / radians / normalized gripper), set `normalization.method: none` and omit `stats_ref`.

## `response.done` (optional)

```yaml
done:
  path: done                     # JSONPath into response body
  type: float                    # bool | float
  threshold: 0.5                 # only when type=float
  scope: chunk                   # MVP: only chunk (per-step deferred)
  action_on_done: auto_stop      # auto_stop (RECORDING) | notify_only
```

Auto-stop is silently downgraded to `notify_only` during READY (no episode to stop) and only fires `episode_stop(stop_reason="model_done")` during RECORDING.

## `loop`

```yaml
loop:
  prefetch_threshold: 0.5        # request next chunk when current is half consumed
  max_inflight: 1                # MVP: pinned at 1 (no overlapping requests)
```

## Adding a new contract

1. Copy `gemma_libero_v1.yaml` to `<your_model>.yaml` and edit field names + URL.
2. Verify your stats are at `${MIMICREC_VLA_DEST_ROOT}/<dataset>/meta/action_stats.json` with the right length (`sum(action.components dims)` — for `[ee_delta, gripper]` that's 7).
3. From the InferencePage UI, the dropdown picks up new files automatically (no backend restart).
4. Use `GET /api/configs/inference/<name>` to see the parsed/validated form (env vars elided).

## Switching to OpenVLA / π0 / RT-2

Most of these accept comparable I/O — write a new YAML matching their field names. Action format may need a future task to support `joint_position` or absolute `ee_pose`.

## Re-exporting legacy datasets recorded before the ee_delta refactor

> **Deployment prerequisite — the inference contract YAML is a separate follow-up.** This PR rewrites the exporter; it does NOT update `gemma_libero_v1.yaml` or the contract decoder. The exported `action_stats.json` has `convention: "q99_derived_midpoint_halfrange"` (mean = (q01+q99)/2, std = (q99-q01)/2 — derived from BOUNDS_Q99, not actual mean/std). The decoder formula `physical = mean + arr * std` happens to be the correct inverse for q99-normalized model outputs in `[-1, +1]`, but the operator-facing contract YAML must be reviewed and confirmed before deploying any model trained from this export to a live robot. Until then, treat exported datasets as training input only.
>
> If a model trained on this export is pointed at the live robot before the YAML follow-up confirms the matching normalization mode, gripper polarity or pose magnitudes may silently invert.

Datasets recorded before the recording-layer change in this PR have
`info.json` `robot_type: "unknown"` and no `gripper_convention` /
`proprio_layout` fields. The exporter rejects these by default to
prevent silent gripper-polarity inversion.

Pass `robot_type=so101` or `robot_type=rebot` (the `robot_type`
field on the export API request) to override:

    POST /datasets/<name>/export
    {
      "format": "vla_compat",
      "instruction_template": "{task}",
      "robot_type": "so101"
    }

(`format` is a string-enum value; use the lowercase form `"vla_compat"` — Pydantic rejects `"VLA_COMPAT"` with a 422.)

The override only adds the convention + layout the exporter would have
read from `info.json`. The output `info.json` is written with
`robot_type` set to the real adapter class name (e.g. `SO101Adapter`).
