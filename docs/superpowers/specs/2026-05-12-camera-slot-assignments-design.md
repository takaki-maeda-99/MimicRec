# Camera Slot Assignments Design

**Date:** 2026-05-12
**Goal:** Decouple the dataset's `observation.images.<name>` key from the physical device's yaml config name. Operators define a global vocabulary of camera **slots** (`front`, `wrist`, `top`, ...) and, per session, decide which physical device fills each slot. The dataset key is the slot name, so the same `observation.images.front` can be filled by an OpenCV USB camera in one session and a GoPro in the next — the model trains on "the front camera" regardless of source.

## Background

### Current behavior

`backend/mimicrec/api/deps.py:107-156` reads `req.cameras: list[str]` and `req.gopros: list[str]` (yaml basenames in `configs/cameras/` and `configs/gopros/`) and uses each name directly as the dataset key. `init_dataset` writes `observation.images.<cam_name>` features (`backend/mimicrec/recording/dataset_layout.py:78-95`), and `CameraManager`'s internal cams dict is keyed the same way. Schema enforcement (`deps.py:281-298`) requires future sessions on a dataset to provide the exact same `cameras + gopros` set as info.json's image_keys.

This makes `name` a dual-purpose field: physical adapter identity AND dataset key. The two cannot be changed independently. To save a GoPro as `observation.images.front`, an operator would need to duplicate the GoPro yaml under a `front` basename — and then they cannot also keep a USB camera named `front`.

### Why a slot system

The operator wants to record a dataset where the `front` view is taken by a GoPro in some sessions and a USB cam in others. The model's input layout is fixed (`observation.images.front`); the hardware that feeds it varies.

## Architecture

### Concept

- **Slot**: a globally-defined output role (`front`, `wrist`, ...). Listed in `configs/camera_roles.yaml`. A slot is the path component used in `observation.images.<slot>` and in the on-disk video directory `videos/observation.images.<slot>/`.
- **Device config**: yaml in `configs/cameras/` or `configs/gopros/`. Defines the adapter target, USB id, GoPro serial, resolution, etc. The yaml's `name` field stays the physical adapter identity (used by `SimCamera` for ZMQ topic subscription, by GoPro logging, etc.) and MUST NOT be conflated with the slot.
- **Slot assignment**: a per-session pair `(slot, device)`. The session creates an adapter from the device's yaml, then registers it under the slot key.

Adapter identity and dataset slot are deliberately separated. `kwargs["name"] = slot` was rejected during design review because `SimCamera` (`backend/mimicrec/cameras/sim_camera.py:35`) reads `name` to pick a ZMQ topic; overriding it would silently break sim inputs.

For OpenCV cameras the separation is mechanical: `CameraManager._cameras` is a `dict[name, adapter]` and the key is already the only thing that flows into dataset paths and preview WS. Passing the slot as the dict key (`cams[slot] = adapter`) is the entire change; the adapter keeps its yaml-defined `name`.

For GoPros the separation needs explicit plumbing. `GoProDeviceRegistry` currently keys `_recorders` / `_previews` / `gopro_specs()` by `d.name`, and `GoProRecorder.stop_episode` writes `cam_name=self._device.name` into the DL sidecar (`backend/mimicrec/gopro/recorder.py:177`). Those are the values that DLWorker uses to compute the on-disk video path. The registry constructor therefore takes a list of `(slot, device)` pairs:

```python
class GoProDeviceRegistry:
    def __init__(self, devices: list[tuple[str, GoProDevice]], ...):
        # tuple is (slot, device). slot is the dataset key; device.name
        # stays the physical adapter identity used for logging and USB.
```

`GoProRecorder` takes the slot as a separate field and writes it as `cam_name` on the sidecar. `gopro_specs()` is keyed by slot. The result: every value that DLWorker / commit_episode / pending dir touches uses the slot, while `device.name` and `device.usb_serial` continue to identify the physical hardware in logs and USB ops.

### Global slot vocabulary

`configs/camera_roles.yaml`:

```yaml
roles:
  - front
  - wrist
  - top
  - side
  - gripper
```

Slot names must match `^[A-Za-z0-9_\-]+$` (path-safe, no slashes or dots). The vocabulary is intentionally small; adding a role is a one-line yaml edit.

### Existing dataset compatibility

A dataset created before this feature has image_keys that may not be in `camera_roles.yaml` (e.g., `a3` has `gopro_external`). These keys are accepted as **legacy slot names** automatically: validation passes a slot if it is in `declared_roles` OR in the existing dataset's info.json image_keys. No migration is required.

## API

### Request schema

`backend/mimicrec/api/schemas.py`:

```python
class SlotAssignment(BaseModel):
    slot: str    # role name, becomes observation.images.<slot>
    device: str  # yaml basename in configs/cameras/ or configs/gopros/

class _BaseSessionRequest(BaseModel):
    dataset: str
    task: str
    robot: str
    fps: int = 30
    preview_enabled: bool = True
    slot_assignments: list[SlotAssignment] = Field(default_factory=list)
    # Deprecated input fields kept for backward compat — a request that
    # provides only the legacy lists is rewritten by the backend shim
    # below into the equivalent slot_assignments.
    cameras: list[str] = Field(default_factory=list)
    gopros: list[str] = Field(default_factory=list)
```

### Response payloads

`SessionStatePayload` keeps `cameras: list[str]` and `gopros: list[str]` as deprecated mirrors. With the new design they hold **slot names** filtered by kind:

- `cameras = [s for s,k,_,_ in resolved if k == "camera"]`
- `gopros  = [s for s,k,_,_ in resolved if k == "gopro"]`

A new field `image_sources: list[ImageSource]` is the authoritative form for new clients:

```python
class ImageSource(BaseModel):
    slot: str
    device: str
    kind: Literal["camera", "gopro"]

class SessionStatePayload(BaseModel):
    ...
    image_sources: list[ImageSource] = Field(default_factory=list)
```

`RecordPage` / `ReplayPage` need no changes: `episode.cameras` metadata already contains every slot (via `_episode_image_sources`, fixed by the earlier preview-toggle work), and the existing `[...cameras, ...gopros].map` block iterates slot names just fine. Migration of the frontend to `image_sources` is a follow-up, not part of this spec.

### New endpoints

- `GET /api/configs/camera_roles` → `{"roles": ["front","wrist",...]}`. Reads `configs/camera_roles.yaml`.
- `GET /api/datasets/{ds}/schema` → `{"image_keys": ["front","wrist","gopro_external"]}`. Reads `meta/info.json` and extracts keys with prefix `observation.images.`. This is the source of truth for existing-dataset slot rows in the frontend; `useEpisodes` is insufficient because a dataset with zero episodes still has a schema.

## Backend validation

In `deps.create_session_from_request`, after loading the dataset path and before instantiating any adapter:

1. Load `configs/camera_roles.yaml` → `declared_roles`.
2. **Backward-compat shim**: if `req.slot_assignments` is empty and `req.cameras` or `req.gopros` is non-empty, rewrite as
   `req.slot_assignments = [SlotAssignment(slot=n, device=n) for n in (*req.cameras, *req.gopros)]`.
   Old clients keep working until the deprecated fields are removed. If the same basename appears in both `cameras` and `gopros` (a configuration mistake), the duplicate slot check in step 3 OR the duplicate device basename check in step 5 catches it as 400.
3. Reject duplicate slot names (HTTP 400).
4. For each slot, reject if `slot` fails the path-safe regex OR is in neither `declared_roles` nor `existing_image_keys` (HTTP 400).
5. For each device:
   - Reject if the same device basename is assigned to two different slots in the same request (HTTP 400). Physical-ID uniqueness in step 6 catches OpenCV `device_id` and GoPro `usb_serial` collisions, but does not catch yamls without a physical ID (mocks, sim cameras), so the basename check is a strict superset.
   - Reject if the basename exists in both `cameras/` and `gopros/` (HTTP 400, ambiguous).
   - Reject if it exists in neither (HTTP 400, not found).
   - Load the yaml; do NOT override `name`. The slot is the dict key in `cams` and the slot/device pair fed to `GoProDeviceRegistry`; the yaml's `name` stays on the adapter.
6. **Physical-ID uniqueness across resolved devices** (HTTP 400 each):
   - OpenCV cameras: `device_id` must be unique.
   - GoPros: `usb_serial` must be unique. (This duplicates `GoProDeviceRegistry`'s existing check at `gopro/registry.py:30` deliberately — the early check yields a friendlier error before the registry is built.)
7. **Orphan GoPro sidecar check**: list `*.json` under `paths.pending_dir/gopro_dl/`. For each sidecar:
   - If the file cannot be parsed as JSON or as `GoProDLJob`, reject with HTTP 409. A corrupt sidecar may reference any cam_name; refusing to start until the operator inspects it is safer than guessing.
   - If `cam_name` is not in the requested slot set, reject with HTTP 409: `orphan GoPro sidecar <file> (cam_name=<x>) does not match this session's slots <list>`. The operator must end the previous session cleanly or move the file aside. Automatic discard was considered and rejected: silently throwing away a downloaded mp4 because the next session picked different slots is too easy to do by mistake.
8. Build the resolved tuple list `[(slot, device, kind, cfg, adapter), ...]` where `device` is the requested basename, `kind` is `"camera"` or `"gopro"`, `cfg` is the yaml content dict, and `adapter` is the instantiated object. All subsequent steps reference fields from these tuples by position or by the destructured loop variables shown.
9. `init_dataset` arguments are derived from the resolved list:
   - `camera_names = [s for s,_,k,_,_ in resolved if k == "camera"]`
   - `gopro_specs = {s: adapter.get_spec() for s,_,k,_,adapter in resolved if k == "gopro"}`
   - `camera_resolutions = {s: (int(cfg["width"]), int(cfg["height"])) for s,_,k,cfg,_ in resolved if k == "camera"}`
   OpenCV and GoPro features stay in their existing separate loops in `dataset_layout.init_dataset`.
10. Persist into `app.state.session_meta`:
    - `slot_assignments: [{"slot": s, "device": d, "kind": k} for s,d,k,_,_ in resolved]` — for state payloads.
    - `cameras = [s for s,_,k,_,_ in resolved if k == "camera"]` and `gopros = [s for s,_,k,_,_ in resolved if k == "gopro"]` mirror filled with slot names by kind.
11. Persist into `app.state.resolved_config["slot_assignments"]`: `[{"slot": s, "device": d, "kind": k, "device_config": cfg} for s,d,k,cfg,_ in resolved]`. The adapter object itself is not serialized; only the cfg dict from yaml. This snapshot lets an episode's `meta/info.json` record exactly what hardware produced it.

### State payload builders

`backend/mimicrec/api/routes/session.py::build_state_payload` and `backend/mimicrec/api/ws/session_hub.py::_build_ws_state` both read from `app.state.session_meta` to build their state dicts. Both need the same update: read `session_meta["slot_assignments"]` and emit it under the new `image_sources` key of the payload. Both keep emitting the deprecated `cameras` / `gopros` mirror straight from `session_meta` so old clients continue to work.

```python
# routes/session.py (and the same shape in ws/session_hub.py)
return SessionStatePayload(
    ...
    cameras=meta.get("cameras", []),    # slot names with kind=camera
    gopros=meta.get("gopros", []),      # slot names with kind=gopro
    image_sources=meta.get("slot_assignments", []),  # NEW
    ...
)
```

The integration tests below pin both REST and WS responses to include `image_sources` with the correct shape.

## Frontend

### Stores

`frontend/src/state/record-form-store.ts`:

```typescript
interface SlotAssignmentDraft {
  slot: string;
  device: string;
}

export interface RecordFormDraft {
  ... // mode, robot, teleop, mapper, dataset, task, fps, autoCycle, ...
  slotAssignments: SlotAssignmentDraft[];
}
```

`selectedCams` and `selectedGopros` are removed. The store reset clears `slotAssignments` to `[]`.

`frontend/src/state/session-store.ts` adds `imageSources: ImageSource[]` hydrated from the WS / REST payload. The legacy `cameras` and `gopros` arrays are kept (mirroring the deprecated payload fields) so RecordPage / ReplayPage continue to work without touching their iteration logic.

### Session config form

`SessionConfigForm.tsx` replaces the two `Cameras` / `GoPros` multi-select blocks with one **Camera Assignments** section:

```
Camera Assignments
┌─────────────────────────────────────────────────────────────────┐
│ Slot: [front ▾]   Device: [gopro_external (GoPro) ▾]    [✕]   │
│ Slot: [wrist ▾]   Device: [mock_cam (Camera) ▾]         [✕]   │
│ + Add slot                                                       │
└─────────────────────────────────────────────────────────────────┘
```

Behavior:

- **Existing dataset** (resolved by `useDatasetSchema(dataset)`): rows are pre-populated from `image_keys`. Slot dropdown is `disabled` for each row (the dataset's schema is fixed). The user can only change which device fills the slot.
- **New dataset**: rows start empty. `+ Add slot` opens a slot dropdown listing roles from `useCameraRoles()` that are not already used in another row.
- Slot dropdown options: `roles ∪ (existing_image_keys \ roles)`. The latter are tagged `(legacy)` in the label so it is obvious why `gopro_external` is offered for an old dataset but not a new one.
- Device dropdown: `useConfigsWithContent("cameras")` and `useConfigsWithContent("gopros")` are concatenated. A device already selected by another row in the same form is `disabled` with an `(in use)` suffix — backend rejects this anyway, but disabling at submit time saves a round trip and shows the conflict immediately.

`handleStart` body:

```typescript
const body = {
  mode, dataset, task, robot, fps,
  slot_assignments: slotAssignments.map(a => ({slot: a.slot, device: a.device})),
  // cameras / gopros omitted — backend shim is for legacy clients only
  ...
};
```

### API hooks

```typescript
export function useCameraRoles() {
  return useQuery<{roles: string[]}>({
    queryKey: ["camera-roles"],
    queryFn: () => apiFetch("/api/configs/camera_roles"),
  });
}

export function useDatasetSchema(dataset: string | undefined) {
  return useQuery<{image_keys: string[]}>({
    queryKey: ["dataset-schema", dataset],
    queryFn: () => apiFetch(`/api/datasets/${dataset}/schema`),
    enabled: !!dataset,
  });
}
```

## Tests

### Backend unit

| File | Cases |
|---|---|
| `tests/unit/test_schemas_slot_assignments.py` | `SlotAssignment` parses, `_BaseSessionRequest.slot_assignments` accepts a list, legacy `cameras`/`gopros` still accepted by the schema. |
| `tests/unit/test_camera_roles_loader.py` | Loader returns the role list; `_SLOT_NAME_RE` accepts `front`/`wrist_2`/`top-1`, rejects `foo/bar`/`foo.bar`/empty. |
| `tests/unit/test_deps_slot_validation.py` | (a) legacy `cameras`/`gopros` shim normalizes to `slot_assignments`; (b) duplicate slot → 400; (c) slot not in roles+image_keys → 400; (d) missing device → 400; (e) device ambiguous (both cameras/ and gopros/) → 400; (f) duplicate device basename across slots → 400 (catches mocks/SimCamera that have no physical ID); (g) duplicate OpenCV `device_id` → 400; (h) duplicate GoPro `usb_serial` → 400; (i) path-unsafe slot name → 400. |
| `tests/unit/test_deps_orphan_sidecar.py` | A sidecar with `cam_name="ghost"` makes session start 409 when slots are `{front, wrist}`; same sidecar passes when slots are `{ghost, front}`. A corrupt (unparseable) sidecar makes session start 409 regardless of slot set. |
| `tests/unit/test_gopro_registry_slot_aware.py` | Construct `GoProDeviceRegistry(devices=[(slot, device), ...])`. `_recorders`, `_previews`, `gopro_specs()` are all keyed by slot. `GoProRecorder.stop_episode` writes `cam_name=slot` (not `device.name`) into the sidecar. |
| `tests/unit/test_state_payload_image_sources.py` | `build_state_payload` and `_build_ws_state` both include `image_sources: [{slot, device, kind}]`. Legacy `cameras` / `gopros` mirror contains the kind-filtered slot names. |
| `tests/unit/test_deps_init_dataset_slot.py` | `init_dataset` receives `camera_names` containing only OpenCV slots; `gopro_specs` keyed by slot name; `camera_resolutions` keyed by slot name with values from the yaml. |
| `tests/unit/test_deps_resolved_config.py` | `app.state.resolved_config["slot_assignments"]` contains each device's full yaml snapshot. |

### Backend integration

| File | Cases |
|---|---|
| `tests/integration/test_slot_assignment_end_to_end.py` | (a) New dataset, `slot_assignments=[{front, gopro_external}, {wrist, mock_cam}]` → info.json image_keys == `{front, wrist}`, video files land in `observation.images.front/`, `observation.images.wrist/`. (b) Second session on the same dataset: change device for `front` to `mock_gopro` → succeeds, mp4 lands under `observation.images.front/`. (c) Second session with a different slot set → 400. |
| `tests/integration/test_dataset_schema_endpoint.py` | `GET /api/datasets/{ds}/schema` returns image_keys even when the dataset has zero recorded episodes (init_dataset has run, episodes/ is empty). |
| `tests/integration/test_camera_roles_endpoint.py` | `GET /api/configs/camera_roles` returns the roles list from yaml. |
| `tests/integration/test_legacy_cameras_compat.py` | A request body using only legacy `cameras: [...]` / `gopros: [...]` (no slot_assignments) still starts a session and records correctly via the shim. |

### Frontend light

- `record-form-store` defaults `slotAssignments=[]`, add / remove / set helpers work.
- `SessionConfigForm.handleStart` includes `slot_assignments` in the body and omits the legacy lists.
- `useCameraRoles` / `useDatasetSchema` hooks call the correct endpoints.

`RecordPage` and `ReplayPage` rendering is verified manually because the existing `episode.cameras` iteration path is unchanged.

### Manual verification checklist

1. New dataset, slot `front` assigned to `gopro_external`. Record one episode. `videos/observation.images.front/episode_000000.mp4` exists; `meta/info.json` `features` contains `observation.images.front`.
2. Same dataset, second session, slot `front` assigned to `mock_cam`. Recording succeeds. The new mp4 lands under `observation.images.front/`. info.json schema is unchanged.
3. Existing `a3` dataset (image_keys = `{wrist, gopro_external}`). Open session config: rows for `wrist` and `gopro_external (legacy)` appear, slot dropdowns disabled, device dropdowns populated. Recording continues to work.
4. Old frontend (sending only `cameras: ["front", "wrist"]`) starts a session. The shim normalizes it; episode metadata's `cameras` field still lists `front` and `wrist`.
5. Same device assigned to two slots in the form. The second slot's device dropdown shows the first slot's device as `(in use)` disabled.

## Out of scope (explicit)

- Migrating existing datasets' image_keys to the global vocabulary. They keep their current keys and are accepted as legacy slots.
- Removing the deprecated `cameras` / `gopros` fields from request and response schemas. The shim is permanent until a future cleanup spec.
- Frontend migration from `cameras`/`gopros` mirror to `image_sources`. Tile rendering keeps using the legacy mirror; replacing it is a follow-up.
- Mid-session changes to slot assignments. Slots are fixed for the session.
- Drag-and-drop reordering of slot rows. Row order is cosmetic; the dataset schema is determined by slot name, not array index.

## Risk and rollout

- Default behavior for clients that omit `slot_assignments` is unchanged: the shim turns their legacy lists into the equivalent assignments. Once the new frontend ships, the legacy lists are not sent anymore but the backend keeps accepting them.
- Existing datasets continue to work because their image_keys count as legacy slots. The unit and integration tests above pin both new and legacy paths.
- The orphan-sidecar 409 is the only new way a session start can fail that did not exist before. The error message is explicit about how to recover (end the previous session cleanly or move the file). This is intentionally noisier than silent recovery because the alternative (auto-discard) was judged too dangerous during design review.
