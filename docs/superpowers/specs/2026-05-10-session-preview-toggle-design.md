# Session-level Live Preview Toggle Design

**Date:** 2026-05-10
**Goal:** Add a per-session toggle that disables the live image preview pipeline (WS fan-out for OpenCV cameras + UDP MPEG-TS preview for GoPros) without affecting recording. The primary motivation is debugging GoPro DL/ffmpeg failures by ruling out USB-CDC-NCM bandwidth contention and CPU pressure from preview decoding/encoding. Secondary use cases: low-resource hosts, headless capture sessions.

## Background

### Current preview pipeline

OpenCV cameras and GoPro previews share a unified surface inside `CameraManager`:

- `OpenCVCamera.read()` returns the same `Frame` that gets recorded; `_run_camera` (`backend/mimicrec/cameras/manager.py:75-97`) stores it via `LatestValue` AND fans it out to WS subscribers as a JPEG.
- `GoProPreviewSource.read()` returns `Frame(preview_only=True)` from a UDP MPEG-TS decoder thread (`backend/mimicrec/gopro/preview.py`); it is merged into `cams` in `deps.py:154-156` so the same `_run_camera` loop drives the WS preview path. `recording/pending.py:115` skips video write when `preview_only=True`, so GoPro previews never reach the dataset.

The GoPro recording is independent of the preview source: `GoProRecorder` (`backend/mimicrec/gopro/recorder.py`) drives `set_shutter` and enqueues `download_file` jobs via `DLWorker`. Preview and recording share the same `WiredGoPro` HTTP client over USB-CDC-NCM.

### Why a toggle, not a fix

Codex review of the GoPro module surfaced multiple plausible root causes for DL/ffmpeg failures (no `download_file` timeout, fragile `media_list.size`-based resume, hard-coded `-map 0:d:1`). The toggle is **not** a fix for those — it is a diagnostic lever to confirm or rule out preview-pipeline contention before investing in the larger fixes. Once the toggle exists, an A/B test with the same hardware and dataset will tell whether the preview pipeline correlates with DL failures.

The toggle stays in the codebase regardless of the diagnostic outcome: low-resource hosts and headless sessions both benefit.

## API surface

`backend/mimicrec/api/schemas.py`:

```python
class _BaseSessionRequest(BaseModel):
    ...
    preview_enabled: bool = True  # NEW

class SessionStatePayload(BaseModel):
    ...
    preview_enabled: bool = True  # NEW — surfaces in /api/session/state and WS state
```

Default `True` preserves all existing behavior. The flag can only be set at session start; mid-session toggle is out of scope (re-entering `set_preview_stream` and managing WS subscriber lifecycles in flight is more complexity than the diagnostic value justifies).

## Backend implementation

### `cameras/manager.py`

- Add `preview_enabled: bool = True` to `CameraManager.__init__`.
- Gate the JPEG-encode + fan-out block (currently `manager.py:88-97`) behind `if self._preview_enabled:`. The `cam.read()` call and `LatestValue.set` MUST stay unconditional — recording, FK, and replay-safety all depend on `latest()`.
- `subscribe_preview(name)` raises a new `PreviewDisabledError` (subclass of `MimicRecError`) when `preview_enabled=False`. Existing `KeyError` semantics for unknown camera names are preserved.

### `gopro/registry.py`

- Add `preview_enabled: bool = True` to `GoProDeviceRegistry.__init__`.
- In `start()`, when `preview_enabled=False`: skip the `GoProPreviewSource(d, udp_port=…)` instantiation entirely. `_previews` stays an empty dict.
- `preview_sources()` returns `{}` when disabled, so `deps.py`'s `cams[name] = src` merge is a no-op.
- `gopro_specs()` is unchanged — `info.json` features registration still happens, the dataset schema is identical regardless of the flag.
- The recording path (`shutter_on/off`, `media_list`, `download_file` in `DLWorker`) is unaffected because it lives on `GoProDevice`, not `GoProPreviewSource`.

### `api/deps.py`

- Read `req.preview_enabled` and pass it to both `GoProDeviceRegistry(..., preview_enabled=…)` and `CameraManager(..., preview_enabled=…)`.
- Persist into `app.state.session_meta["preview_enabled"]` so REST and WS state payloads can echo it.

### `api/ws/camera_hub.py`

- Catch `PreviewDisabledError` from `subscribe_preview` and close the socket with `code=1008, reason="preview disabled this session"`. The frontend uses this reason to suppress reconnect attempts.

### `api/ws/session_hub.py` and `routes/session.py`

- Include `"preview_enabled": meta.get("preview_enabled", True)` in the state dicts emitted from both REST and WS channels (mirrors how `gopros` is currently propagated).

## Frontend implementation

### `state/record-form-store.ts`

Add `previewEnabled: boolean` (default `true`) to `RecordFormDraft`, mirroring `autoCycle`.

### `state/session-store.ts`

Add `previewEnabled: boolean` to the session state. Hydrate from WS/REST payload via `data.preview_enabled ?? true`.

### `components/SessionConfigForm.tsx`

Add a checkbox inside the existing `border ... bg-surface-soft` block (next to `autoCycle`):

```tsx
<label className="flex items-center gap-2 text-sm font-medium text-charcoal">
  <input
    type="checkbox"
    checked={form.previewEnabled}
    onChange={e => form.set({ previewEnabled: e.target.checked })}
  />
  ライブプレビュー表示（OFF で USB 帯域・CPU を解放）
</label>
```

Include `preview_enabled: form.previewEnabled` in the body sent by `handleStart`.

### `pages/RecordPage.tsx`

When `previewEnabled === false`, replace the `[...cameras, ...gopros].map((cam) => …)` tile grid with a single placeholder element (e.g. a muted-text panel "Live preview disabled for this session"). Tiles disappearing entirely would read as "cameras not detected"; the explicit placeholder removes that ambiguity.

### Camera tile WS hookup

When `previewEnabled === false`, the tile component does not open `/ws/cameras/{name}`. As a defense in depth, if a stale connection attempt does fire, the 1008 close from `camera_hub.py` is treated as terminal — no reconnect.

## Tests

### Backend unit

| File | Cases |
|---|---|
| `tests/unit/cameras/test_manager_preview_toggle.py` (new) | (a) `preview_enabled=False` → `subscribe_preview` raises `PreviewDisabledError`. (b) `_run_camera` does not call `encode_jpeg` (spy). (c) `latest()` is still populated — recording is unaffected. |
| `tests/unit/gopro/test_registry_preview_toggle.py` (new) | (a) `preview_enabled=False` → `MockGoProDevice.start_preview` is never called. (b) `preview_sources()` is `{}`. (c) `gopro_specs()` unchanged. (d) `episode_start`/`episode_stop` still succeed without errors — confirmed by `test_registry_preview_disabled_episode_lifecycle_still_works`. |
| `tests/unit/api/test_schemas_preview_enabled.py` (new) | Default `True`; explicit `False` accepted. Non-bool coercion (e.g. `"yes"` → `True`) is intentionally accepted: `preview_enabled` uses plain `bool` (lax Pydantic v2 mode) for consistency with `success` and `force` fields across the codebase — the strict-rejection test was removed in commit `1322b26`. |

### Backend integration

| File | Cases |
|---|---|
| `tests/integration/test_session_preview_toggle.py` (new) | (a) `POST /api/session/start` with `preview_enabled=False` → `GET /api/session/state` includes `preview_enabled: false`. (b) `/ws/cameras/{name}` closes with code 1008 reason "preview disabled this session". |

### Frontend

Light store + form-submission tests only:
- `record-form-store` defaults `previewEnabled` to `true`.
- `SessionConfigForm.handleStart` includes `preview_enabled` in the request body when toggled off.

`RecordPage` placeholder rendering is verified manually.

### Manual verification checklist

1. Existing YAML, no `preview_enabled` field on the wire → behavior identical to current main.
2. OpenCV 1 + GoPro 1, `preview_enabled=false`: recording succeeds, RecordPage shows placeholder, `journalctl` shows no `preview opening` log entry from `gopro/preview.py`.
3. With `preview_enabled=false`, run 5 consecutive episodes and confirm no DL/ffmpeg failures (this is the original diagnostic motivation — the result either confirms or eliminates preview contention as the cause).

## Out of scope (explicit)

- Mid-session toggle. The fields are immutable for the session.
- Per-camera or per-GoPro granularity. Sessions enable/disable preview as a whole.
- Fixing the GoPro DL/ffmpeg root causes flagged by Codex (timeout/retry, resume strategy, GPMF stream detection). Those are tracked separately; the toggle does not depend on them and they do not depend on the toggle.
- Hydra YAML flag (rejected: contradicts the "toggle at session start" UX).

## Risk and rollout

- Default `True` → zero behavior change for existing clients. Frontend bumps that don't know about the field still get full preview.
- If `preview_enabled=false` exposes a latent bug in `_run_camera` (e.g. an existing consumer was secretly relying on the WS push path side-effect), the unit test for `latest()` population is the canary.
- The PreviewDisabledError → 1008 close behavior is the only new WS contract. Documented in the integration test.
