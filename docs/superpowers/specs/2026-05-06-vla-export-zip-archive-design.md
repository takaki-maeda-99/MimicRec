# VLA-Compat Export: Zip Archive Download

**Status:** design — pending implementation plan
**Author:** takaki, w/ Claude (Opus 4.7)
**Scope:** Add an in-browser zip download path for VLA-compat exports by extending the existing `GET /api/datasets/{ds}/archive` endpoint and the frontend ExportDatasetModal. Server-side directory output (current `POST /api/datasets/{ds}/export`) is unchanged.

## Problem

The VLA-compat exporter only writes to a local directory under `<dest_root>/<dataset_name>/`. To get the result onto another machine, the user has to SSH/rsync/scp the directory off the server. The v3-native format already has a one-click zip download via `GET /api/datasets/{ds}/archive`, but that endpoint explicitly rejects `format=vla_compat` with HTTP 400 (`backend/mimicrec/api/routes/datasets.py:170-177`).

There is no equivalent download for VLA-compat. The user wants to be able to click "Download as zip" in the frontend and get a single archive file.

## Goals (in scope)

1. **`GET /api/datasets/{ds}/archive?format=vla_compat&...` returns an `application/zip` stream** containing the same directory layout that `export_dataset_to_local` writes (`meta/`, `data/chunk-XXX/`, `videos/observation.images.<cam>/chunk-XXX/`).
2. **Frontend ExportDatasetModal exposes the zip path as an output-destination toggle** alongside the existing server-directory output.
3. **No persistent server-side artifact for the zip path.** The conversion runs into a `tempfile.TemporaryDirectory()` that is cleaned up after the response stream finishes.

## Non-goals

- Zipping directly from the recorded dataset without going through a tempdir (premature optimization; the conversion step has to run somewhere).
- Background job / progress streaming for very large datasets. Current export is synchronous and that stays.
- Changing the existing `POST /api/datasets/{ds}/export` JSON response shape or its server-directory output behavior.
- Adding a zip download for the directory output that `POST /export` already produced. (If the user wants that later, a separate `GET /archive?format=vla_compat&from_existing=true` could be added — out of scope here.)
- v3-native archive endpoint behavior is untouched.

## Design

### API surface

Extend the existing archive endpoint in `backend/mimicrec/api/routes/datasets.py`:

```
GET /api/datasets/{ds}/archive
  ?format={lerobot_v3_native | vla_compat}              # default: lerobot_v3_native (unchanged)
  &instruction_template=<urlencoded string>              # vla_compat only, optional
                                                         # default: "What action should the robot take to {TASK}? A:"
                                                         # (matches POST /export default)
  &robot_type={so101 | rebot}                            # vla_compat only, optional override
```

- `format=lerobot_v3_native` → existing behavior, unchanged.
- `format=vla_compat` →
  1. Create `tempfile.TemporaryDirectory()`.
  2. Call `export_dataset_to_local(ds_root=..., dest_root=Path(tmp), format=ExportFormat.VLA_COMPAT, instruction_template=..., force=True, override=ExportOverride(robot_type=...) if robot_type else None)`.
  3. Stream the resulting `<tmp>/<ds>/` tree as a zip via `zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)`, walking the directory and writing each file with an arcname relative to `<tmp>/<ds>/`.
  4. Return `StreamingResponse(generator, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{ds}_vla.zip"'})`.

`force` is hardcoded to `True` for the zip path because the destination is a fresh tempdir each time — the `DestinationExistsError` case cannot occur.

### Tempdir lifetime

The tempdir must outlive the streaming response. The existing v3-native generator builds the entire zip in an in-memory `BytesIO` before yielding (single `yield buf.read()`), which works for our scale (240 episodes is roughly low-GB-range when video is included). For consistency and to avoid lifetime bugs:

- **Buffer in memory** the same way as the v3-native path: build the full zip into a `BytesIO`, then yield. Tempdir lives only for the duration of `export_dataset_to_local` + the zip-write loop, all inside the `with TemporaryDirectory()` block before `StreamingResponse` is returned.
- **Tradeoff acknowledged:** memory peak ≈ raw export size + zip-buffered size. If this becomes a problem (multi-GB exports), follow up with a chunked streaming variant using `BackgroundTask` for cleanup. Out of scope here.

### Validation

- `instruction_template` defaults to the same string as `POST /export` when omitted (no 400 on omission).
- `robot_type` not in `{so101, rebot}` → 422 (FastAPI enum validation if we type the param as `RobotTypeOverride | None`).
- `export_dataset_to_local` raising `ValueError` (e.g., proprio layout missing for an unknown robot_type) → 400 with the underlying message, matching the existing POST `/export` behavior.

### Frontend

`frontend/src/components/ExportDatasetModal.tsx`:

- Add a new fieldset "Output destination" with two radio options:
  - **"Save to server"** (default — current behavior, calls `POST /export`).
  - **"Download as zip"** (new — opens the archive URL).
- When "Download as zip" is selected:
  - The "Overwrite existing destination" checkbox is hidden (no destination conflict possible).
  - Submit triggers `window.location.href = "/api/datasets/{ds}/archive?format=vla_compat&instruction_template=..." + (robotType ? "&robot_type=..." : "")`. The browser handles the download via `Content-Disposition`.
  - The success/error UI panes (which read `exportMutation.data` / `exportMutation.error`) are skipped — the browser owns the response. If the server returns an error, the user sees the browser's default error rendering. (Acceptable for a first cut; can revisit if it confuses users.)
- Format radio (LeRobot v3 native vs. VLA-compat) and the VLA-compat-only fields (instruction template, robot-type override) stay where they are. v3-native + zip download is also a valid combination and works because the existing endpoint already supports it.

### Tests

`tests/api/test_export_routes.py`:

1. `GET /archive?format=vla_compat&instruction_template=...` on a SO-101 fixture dataset → 200, `Content-Type: application/zip`, response body parses as a valid zip, contains expected entries (`meta/info.json`, at least one `data/chunk-000/episode_*.parquet`, at least one `videos/observation.images.*/chunk-000/episode_*.mp4`).
2. Same, with `robot_type=rebot` override on a legacy reBot dataset → 200, zip contains 7-dim proprio in info.json.
3. `GET /archive?format=vla_compat` with no `instruction_template` → 200 (default template applied).
4. `GET /archive?format=vla_compat&robot_type=invalid` → 422 (FastAPI enum validation).
5. v3-native archive path still works (regression — should already be covered by an existing test, otherwise add).

## Implementation footprint

**Backend (1 file)**:
- `backend/mimicrec/api/routes/datasets.py` — replace the current `if format != LEROBOT_V3_NATIVE: raise 400` branch with the vla_compat tempdir + zip-from-tree implementation. Add `instruction_template` and `robot_type` query params.

**Frontend (1 file)**:
- `frontend/src/components/ExportDatasetModal.tsx` — add output-destination radio, branch the submit handler.

**Tests (1 file)**:
- `tests/api/test_export_routes.py` — add the four cases above.

No new modules. No exporter-internals changes. No new dependencies (`zipfile` and `tempfile` are stdlib).
