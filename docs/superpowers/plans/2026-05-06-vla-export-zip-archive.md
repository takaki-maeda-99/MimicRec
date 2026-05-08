# VLA-Compat Zip Archive Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users download a VLA-compat-formatted dataset as a single `.zip` from the browser, by extending `GET /api/datasets/{ds}/archive` and surfacing the path as an output-destination toggle in `ExportDatasetModal`.

**Architecture:** The existing `GET /archive` endpoint streams a zip for `format=lerobot_v3_native` only. We extend it: when `format=vla_compat`, run the existing `export_dataset_to_local` into a `tempfile.TemporaryDirectory()` (with `force=True`, no destination conflict possible), walk the resulting tree, build a zip into an in-memory `BytesIO` inside the `with` block, then return a `StreamingResponse(application/zip)`. Frontend adds a radio for "Save to server" / "Download as zip"; the zip path uses `window.location.href` against the archive URL with query-encoded params.

**Tech Stack:** FastAPI (`StreamingResponse`, `Query`), Python `zipfile`/`tempfile`/`io` stdlib, React + TanStack Query frontend, pytest + httpx ASGITransport for tests.

**Spec:** `docs/superpowers/specs/2026-05-06-vla-export-zip-archive-design.md`

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `backend/mimicrec/api/routes/datasets.py` | HTTP route layer | Modify `download_archive` (lines 165-198): add `instruction_template` and `robot_type` query params, replace the `vla_compat → 400` branch with tempdir-based conversion + zip stream |
| `tests/api/test_export_routes.py` | Route-level integration tests | Append 4 new tests covering VLA-compat zip path |
| `frontend/src/components/ExportDatasetModal.tsx` | Export modal UI | Add "Output destination" radio fieldset; branch `handleSubmit` for the zip path (URL build + `window.location.href`); hide "Overwrite" checkbox when zip is selected |

No new modules. No new dependencies (`zipfile`, `tempfile`, `io`, `pathlib` are stdlib).

---

## Task 1: Backend test — VLA-compat zip happy path (SO-101)

**Files:**
- Test: `tests/api/test_export_routes.py` (append at end)

- [ ] **Step 1: Add the failing test**

Append this test to `tests/api/test_export_routes.py`:

```python
@pytest.mark.asyncio
async def test_archive_vla_compat_returns_zip_so101(app: FastAPI, tmp_path: Path):
    """GET /archive?format=vla_compat should stream a zip containing
    the converted VLA-compat tree. No tempdir or dest_path leaked."""
    import io
    import zipfile
    import pyarrow as pa
    import pyarrow.parquet as pq
    from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
    from mimicrec.recording.metadata import append_episode, upsert_task

    ds_name = "ds_zip_so101"
    ds_root = tmp_path / "datasets" / ds_name
    init_dataset(ds_root, fps=15,
                 joint_names=["j1", "j2", "j3", "j4", "j5", "j6"],
                 camera_names=["front"])
    p = dataset_paths(ds_root)
    upsert_task(p.meta_dir, "pick cube", "pick the cube")
    chunk_dir = p.chunk_dir(0)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    rows = [{
        "timestamp": i / 15, "tick_t_mono_ns": 0,
        "observation.state.joint_pos": [0.1] * 6,
        "observation.state.joint_vel": [0.0] * 6,
        "observation.state.joint_effort": [0.0] * 6,
        "observation.state.t_mono_ns": 0,
        "observation.state.gripper_pos": 0.5,
        "observation.state.ee_pos": [0.1, 0.2, 0.3],
        "observation.state.ee_rotvec": [0.0, 0.0, 0.0],
        "action.joint_pos": [0.2] * 6,
        "action.t_mono_ns": 0,
        "action.gripper_pos": 0.7,
        "frame_index": i, "episode_index": 0, "index": i, "task_index": 0,
        "observation.images.front.video_frame_index": i,
        "observation.images.front.t_mono_ns": 0,
    } for i in range(2)]
    pq.write_table(pa.Table.from_pylist(rows), p.episode_parquet(0, 0))
    cam_dir = p.videos_dir / "observation.images.front" / "chunk-000"
    cam_dir.mkdir(parents=True, exist_ok=True)
    (cam_dir / "episode_000000.mp4").write_bytes(b"\x00fake\x00")
    append_episode(p.meta_dir, {
        "episode_index": 0, "task": "pick cube",
        "num_frames": 2, "robot": "so101", "mode": "teleop",
        "cameras": ["front"],
    })
    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"  # not used by archive path

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get(
            f"/api/datasets/{ds_name}/archive",
            params={"format": "vla_compat", "robot_type": "so101"},
        )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert f'filename="{ds_name}_vla.zip"' in r.headers.get("content-disposition", "")

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert "meta/info.json" in names
    assert any(n.startswith("data/chunk-000/episode_") and n.endswith(".parquet") for n in names)
    assert any(n.startswith("videos/observation.images.front/chunk-000/episode_")
               and n.endswith(".mp4") for n in names)

    # Tempdir must not have leaked into the dest_root
    assert not (tmp_path / "vla").exists() or not any((tmp_path / "vla").iterdir())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/api/test_export_routes.py::test_archive_vla_compat_returns_zip_so101 -v`

Expected: FAIL with HTTP 400 ("format=vla_compat is not supported via the archive download...").

- [ ] **Step 3: Commit**

```bash
git add tests/api/test_export_routes.py
git commit -m "test(api): failing test for VLA-compat zip archive download"
```

---

## Task 2: Backend impl — extend `GET /archive` to handle VLA-compat

**Files:**
- Modify: `backend/mimicrec/api/routes/datasets.py:165-198`

- [ ] **Step 1: Add imports**

At the top of `backend/mimicrec/api/routes/datasets.py`, add `tempfile` and `Literal` if not already imported. The current imports already include `io`, `zipfile`, `Path`, `Query`, `StreamingResponse`. Update:

```python
from __future__ import annotations
import asyncio
import io
import json
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Literal
```

Also extend the schemas import to include `DEFAULT_INSTRUCTION_TEMPLATE` and the `ExportOverride` import already present:

```python
from mimicrec.api.schemas import (
    CreateDatasetRequest, CreateTaskRequest, DatasetSummary,
    EpisodeSummary, ExportFormat, ExportRequest, ExportResponse, TaskSummary,
    DEFAULT_INSTRUCTION_TEMPLATE,
)
```

- [ ] **Step 2: Replace the archive route body**

Replace the entire `download_archive` function (currently `datasets.py:165-198`) with:

```python
@router.get("/datasets/{ds}/archive")
async def download_archive(
    request: Request, ds: str,
    format: ExportFormat = ExportFormat.LEROBOT_V3_NATIVE,
    instruction_template: str = DEFAULT_INSTRUCTION_TEMPLATE,
    robot_type: Literal["so101", "rebot"] | None = None,
):
    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")

    if format == ExportFormat.LEROBOT_V3_NATIVE:
        def generate():
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for path_in_zip, content in build_archive_stream(ds_root):
                    if isinstance(content, Path):
                        zf.write(content, arcname=path_in_zip)
                    else:
                        zf.writestr(path_in_zip, content)
            buf.seek(0)
            yield buf.read()

        return StreamingResponse(
            generate(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{ds}.zip"'},
        )

    # format == VLA_COMPAT: convert into tempdir, then stream the tree as zip.
    def generate_vla():
        buf = io.BytesIO()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            override = ExportOverride(robot_type=robot_type) if robot_type else None
            try:
                export_dataset_to_local(
                    ds_root=ds_root,
                    dest_root=tmp_root,
                    format=ExportFormat.VLA_COMPAT,
                    instruction_template=instruction_template,
                    force=True,
                    override=override,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            converted_root = tmp_root / ds
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for fp in sorted(converted_root.rglob("*")):
                    if fp.is_file():
                        arcname = fp.relative_to(converted_root).as_posix()
                        zf.write(fp, arcname=arcname)
        buf.seek(0)
        yield buf.read()

    return StreamingResponse(
        generate_vla(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{ds}_vla.zip"'},
    )
```

Critical invariants:
- The whole `with TemporaryDirectory()` block lives inside `generate_vla()`. The generator yields the in-memory zip (`buf.read()`) *after* the `with` block has exited and the tempdir is already cleaned up. The `BytesIO` outlives the tempdir because it owns its bytes.
- `force=True` is hardcoded — the destination is always a fresh tempdir.
- `ValueError` from the exporter (e.g., proprio layout missing for unknown robot_type) becomes 400, matching `POST /export` behavior.
- `Literal["so101", "rebot"] | None` makes FastAPI return 422 for invalid values.

- [ ] **Step 3: Run the Task 1 test**

Run: `pytest tests/api/test_export_routes.py::test_archive_vla_compat_returns_zip_so101 -v`

Expected: PASS.

- [ ] **Step 4: Run the full test_export_routes module to confirm no regressions**

Run: `pytest tests/api/test_export_routes.py -v`

Expected: all tests pass (existing 5 + new 1 = 6).

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/api/routes/datasets.py
git commit -m "feat(api): VLA-compat zip download via GET /archive

Convert into a tempdir, walk + zip into memory, stream as
application/zip. Tempdir is fully cleaned up before the
response stream yields."
```

---

## Task 3: Backend test — reBot legacy override

**Files:**
- Test: `tests/api/test_export_routes.py` (append)

- [ ] **Step 1: Add the test**

Append:

```python
@pytest.mark.asyncio
async def test_archive_vla_compat_with_rebot_override(app: FastAPI, tmp_path: Path):
    """robot_type=rebot override on a legacy 'unknown' dataset must
    produce a 7-dim proprio info.json inside the zip."""
    import io
    import json
    import zipfile
    import pyarrow as pa
    import pyarrow.parquet as pq
    from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
    from mimicrec.recording.metadata import append_episode, upsert_task

    ds_name = "legacy_rebot"
    ds_root = tmp_path / "datasets" / ds_name
    init_dataset(ds_root, fps=15,
                 joint_names=["j1", "j2", "j3", "j4", "j5", "j6"],
                 camera_names=["front"])
    p = dataset_paths(ds_root)
    upsert_task(p.meta_dir, "pick cube", "pick the cube")
    chunk_dir = p.chunk_dir(0)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    rows = [{
        "timestamp": i / 15, "tick_t_mono_ns": 0,
        "observation.state.joint_pos": [0.1] * 6,
        "observation.state.joint_vel": [0.0] * 6,
        "observation.state.joint_effort": [0.0] * 6,
        "observation.state.t_mono_ns": 0,
        "observation.state.gripper_pos": 0.5,
        "observation.state.ee_pos": [0.1, 0.2, 0.3],
        "observation.state.ee_rotvec": [0.0, 0.0, 0.0],
        "action.joint_pos": [0.2] * 6,
        "action.t_mono_ns": 0,
        "action.gripper_pos": 0.7,
        "frame_index": i, "episode_index": 0, "index": i, "task_index": 0,
        "observation.images.front.video_frame_index": i,
        "observation.images.front.t_mono_ns": 0,
    } for i in range(2)]
    pq.write_table(pa.Table.from_pylist(rows), p.episode_parquet(0, 0))
    cam_dir = p.videos_dir / "observation.images.front" / "chunk-000"
    cam_dir.mkdir(parents=True, exist_ok=True)
    (cam_dir / "episode_000000.mp4").write_bytes(b"\x00fake\x00")
    append_episode(p.meta_dir, {
        "episode_index": 0, "task": "pick cube",
        "num_frames": 2, "robot": "rebot", "mode": "teleop",
        "cameras": ["front"],
    })
    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get(
            f"/api/datasets/{ds_name}/archive",
            params={"format": "vla_compat", "robot_type": "rebot"},
        )
    assert r.status_code == 200, r.text
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    info = json.loads(zf.read("meta/info.json").decode())
    assert info["robot_type"] == "ReBotArmZmqAdapter"
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/api/test_export_routes.py::test_archive_vla_compat_with_rebot_override -v`

Expected: PASS (no impl change needed; this exercises the same branch with a different override).

- [ ] **Step 3: Commit**

```bash
git add tests/api/test_export_routes.py
git commit -m "test(api): VLA-compat zip honors rebot robot_type override"
```

---

## Task 4: Backend test — invalid robot_type returns 422

**Files:**
- Test: `tests/api/test_export_routes.py` (append)

- [ ] **Step 1: Add the test**

```python
@pytest.mark.asyncio
async def test_archive_vla_compat_rejects_invalid_robot_type(app: FastAPI, tmp_path: Path):
    """FastAPI Literal validation must reject robot_type values
    outside {so101, rebot} with 422 before any exporter code runs."""
    from mimicrec.recording.dataset_layout import init_dataset

    ds_name = "ds_validate"
    init_dataset(tmp_path / "datasets" / ds_name, fps=15,
                 joint_names=["j1", "j2", "j3", "j4", "j5", "j6"],
                 camera_names=[])
    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get(
            f"/api/datasets/{ds_name}/archive",
            params={"format": "vla_compat", "robot_type": "totally_invalid"},
        )
    assert r.status_code == 422
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/api/test_export_routes.py::test_archive_vla_compat_rejects_invalid_robot_type -v`

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/api/test_export_routes.py
git commit -m "test(api): VLA-compat archive validates robot_type via Literal"
```

---

## Task 5: Backend test — default instruction_template applied when omitted

**Files:**
- Test: `tests/api/test_export_routes.py` (append)

- [ ] **Step 1: Add the test**

```python
@pytest.mark.asyncio
async def test_archive_vla_compat_uses_default_instruction_template(app: FastAPI, tmp_path: Path):
    """Omitting instruction_template must apply the same default as
    POST /export (DEFAULT_INSTRUCTION_TEMPLATE), not 400."""
    import io
    import pyarrow as pa
    import pyarrow.parquet as pq
    import zipfile
    from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
    from mimicrec.recording.metadata import append_episode, upsert_task

    ds_name = "ds_default_template"
    ds_root = tmp_path / "datasets" / ds_name
    init_dataset(ds_root, fps=15,
                 joint_names=["j1", "j2", "j3", "j4", "j5", "j6"],
                 camera_names=["front"])
    p = dataset_paths(ds_root)
    upsert_task(p.meta_dir, "pick cube", "pick the cube")
    chunk_dir = p.chunk_dir(0)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    rows = [{
        "timestamp": i / 15, "tick_t_mono_ns": 0,
        "observation.state.joint_pos": [0.1] * 6,
        "observation.state.joint_vel": [0.0] * 6,
        "observation.state.joint_effort": [0.0] * 6,
        "observation.state.t_mono_ns": 0,
        "observation.state.gripper_pos": 0.5,
        "observation.state.ee_pos": [0.1, 0.2, 0.3],
        "observation.state.ee_rotvec": [0.0, 0.0, 0.0],
        "action.joint_pos": [0.2] * 6,
        "action.t_mono_ns": 0,
        "action.gripper_pos": 0.7,
        "frame_index": i, "episode_index": 0, "index": i, "task_index": 0,
        "observation.images.front.video_frame_index": i,
        "observation.images.front.t_mono_ns": 0,
    } for i in range(2)]
    pq.write_table(pa.Table.from_pylist(rows), p.episode_parquet(0, 0))
    cam_dir = p.videos_dir / "observation.images.front" / "chunk-000"
    cam_dir.mkdir(parents=True, exist_ok=True)
    (cam_dir / "episode_000000.mp4").write_bytes(b"\x00fake\x00")
    append_episode(p.meta_dir, {
        "episode_index": 0, "task": "pick cube",
        "num_frames": 2, "robot": "so101", "mode": "teleop",
        "cameras": ["front"],
    })
    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        # Note: no instruction_template param.
        r = await ac.get(
            f"/api/datasets/{ds_name}/archive",
            params={"format": "vla_compat", "robot_type": "so101"},
        )
    assert r.status_code == 200, r.text
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert "meta/info.json" in zf.namelist()
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/api/test_export_routes.py::test_archive_vla_compat_uses_default_instruction_template -v`

Expected: PASS.

- [ ] **Step 3: Run the full module one more time**

Run: `pytest tests/api/test_export_routes.py -v`

Expected: 9 tests pass (5 existing + 4 new).

- [ ] **Step 4: Commit**

```bash
git add tests/api/test_export_routes.py
git commit -m "test(api): VLA-compat archive defaults instruction_template"
```

---

## Task 6: Frontend — output-destination toggle in ExportDatasetModal

**Files:**
- Modify: `frontend/src/components/ExportDatasetModal.tsx`

- [ ] **Step 1: Replace the modal component**

Open `frontend/src/components/ExportDatasetModal.tsx` and replace the entire file with:

```tsx
import { useState } from "react";
import { useExportDataset, useTasks } from "../api/queries.ts";
import { ApiError } from "../api/client.ts";
import type { ExportFormat, RobotTypeOverride } from "../api/types.ts";

const DEFAULT_TEMPLATE = "What action should the robot take to {TASK}? A:";

type Destination = "server" | "zip";

interface Props {
  ds: string;
  onClose: () => void;
}

export function ExportDatasetModal({ ds, onClose }: Props) {
  const [format, setFormat] = useState<ExportFormat>("vla_compat");
  const [destination, setDestination] = useState<Destination>("server");
  const [template, setTemplate] = useState<string>(DEFAULT_TEMPLATE);
  const [force, setForce] = useState<boolean>(false);
  const [needsForce, setNeedsForce] = useState<boolean>(false);
  const [robotType, setRobotType] = useState<"" | RobotTypeOverride>("");
  const exportMutation = useExportDataset(ds);
  const { data: tasks } = useTasks(ds);

  const handleSubmit = () => {
    setNeedsForce(false);
    if (destination === "zip") {
      const params = new URLSearchParams({ format });
      if (format === "vla_compat") {
        params.set("instruction_template", template);
        if (robotType) params.set("robot_type", robotType);
      }
      window.location.href = `/api/datasets/${encodeURIComponent(ds)}/archive?${params.toString()}`;
      return;
    }
    exportMutation.mutate(
      {
        format,
        instruction_template: template,
        force,
        ...(robotType ? { robot_type: robotType } : {}),
      },
      {
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            setNeedsForce(true);
            setForce(true);
          }
        },
      },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-[640px] rounded-lg bg-white p-6 shadow-xl">
        <h2 className="mb-4 text-lg font-semibold">Export "{ds}"</h2>

        <fieldset className="mb-4">
          <legend className="mb-2 text-sm font-medium">Format</legend>
          <label className="mb-1 flex items-center gap-2">
            <input type="radio" checked={format === "lerobot_v3_native"}
                   onChange={() => setFormat("lerobot_v3_native")} />
            LeRobot v3 native (raw recorded columns)
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" checked={format === "vla_compat"}
                   onChange={() => setFormat("vla_compat")} />
            VLA-compat (EE-delta + gripper, instruction-conditioned)
          </label>
        </fieldset>

        <fieldset className="mb-4">
          <legend className="mb-2 text-sm font-medium">Output destination</legend>
          <label className="mb-1 flex items-center gap-2">
            <input type="radio" checked={destination === "server"}
                   onChange={() => setDestination("server")} />
            Save to server (writes to <code className="text-xs">vla_dest_root</code>)
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" checked={destination === "zip"}
                   onChange={() => setDestination("zip")} />
            Download as zip (browser file download)
          </label>
        </fieldset>

        {format === "vla_compat" && (
          <>
            <label className="mb-1 block text-sm font-medium">Instruction template</label>
            <textarea className="mb-2 w-full rounded border border-gray-300 p-2 text-sm"
                      rows={2} value={template}
                      onChange={(e) => setTemplate(e.target.value)} />
            <p className="mb-4 text-xs text-gray-500">
              <code>{"{TASK}"}</code> is replaced per episode with each task's instruction
              (or task name when instruction is empty).
            </p>

            <label className="mb-1 block text-sm font-medium">Robot-type override (legacy datasets)</label>
            <select className="mb-1 w-full rounded border border-gray-300 p-2 text-sm"
                    value={robotType}
                    onChange={(e) => setRobotType(e.target.value as "" | RobotTypeOverride)}>
              <option value="">Auto (use info.json)</option>
              <option value="so101">SO-101</option>
              <option value="rebot">reBot</option>
            </select>
            <p className="mb-4 text-xs text-gray-500">
              Set this only if the export fails because <code>info.json</code> declares
              <code className="mx-1">robot_type=&quot;unknown&quot;</code>
              (datasets recorded before adapter declarations were tracked).
            </p>

            <div className="mb-4 max-h-32 overflow-auto rounded border border-gray-200 p-2 text-xs">
              <div className="mb-1 font-medium">Tasks in this dataset:</div>
              {tasks?.map((t) => (
                <div key={t.task_index} className="flex justify-between gap-3 py-0.5">
                  <span className="font-mono">{t.task}</span>
                  <span className={t.instruction ? "text-gray-700" : "text-amber-600"}>
                    {t.instruction || "(no instruction — will fall back to task name)"}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}

        {destination === "server" && needsForce && (
          <div className="mb-3 rounded bg-amber-50 p-2 text-sm text-amber-800">
            Destination already exists. Tick "Overwrite" and submit again to replace it.
          </div>
        )}
        {destination === "server" && (
          <label className="mb-4 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={force}
                   onChange={(e) => setForce(e.target.checked)} />
            Overwrite existing destination
          </label>
        )}

        {destination === "server" && exportMutation.isSuccess && (
          <div className="mb-3 rounded bg-green-50 p-2 text-sm text-green-800">
            Exported {exportMutation.data.num_episodes} episodes
            ({exportMutation.data.num_frames} frames) to{" "}
            <code>{exportMutation.data.dest_path}</code>
            {exportMutation.data.warnings.length > 0 && (
              <ul className="mt-1 list-disc pl-4 text-xs text-amber-700">
                {exportMutation.data.warnings.map((w) => <li key={w}>{w}</li>)}
              </ul>
            )}
          </div>
        )}
        {destination === "server" && exportMutation.isError && !needsForce && (
          <div className="mb-3 rounded bg-red-50 p-2 text-sm text-red-800">
            {exportMutation.error.message}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button className="rounded border border-gray-300 px-3 py-1 text-sm" onClick={onClose}>
            Close
          </button>
          <button className="rounded bg-blue-600 px-3 py-1 text-sm text-white disabled:opacity-50"
                  disabled={destination === "server" && exportMutation.isPending}
                  onClick={handleSubmit}>
            {destination === "server" && exportMutation.isPending
              ? "Exporting…"
              : destination === "zip"
                ? "Download zip"
                : "Export"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

Notes:
- `destination === "zip"` path bypasses the mutation entirely — the browser handles the download via `Content-Disposition`.
- Force checkbox, success/error panes, and "Exporting…" pending text are hidden on the zip path because they're irrelevant.
- The submit button label flips between "Download zip" and "Export" depending on destination.

- [ ] **Step 2: Type-check the frontend**

Run: `cd frontend && npx tsc --noEmit`

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ExportDatasetModal.tsx
git commit -m "feat(frontend): output-destination toggle for VLA-compat export

Adds 'Save to server' / 'Download as zip' radio. Zip path
builds the archive URL from current form state and triggers
the download via window.location.href; success/error panes
are hidden on that path because the browser owns the response."
```

---

## Task 7: Manual UI verification

**Files:** none (verification only)

- [ ] **Step 1: Start backend + frontend**

In one terminal:
```bash
cd backend && python -m mimicrec.api.app
```

In another:
```bash
cd frontend && npm run dev
```

- [ ] **Step 2: Verify the four scenarios**

Open the dev URL in a browser and load any existing VLA-compat-capable dataset. For each:

1. **Server dir, VLA-compat (regression)**: Format=VLA-compat, Destination=Save to server, Submit. Check the success panel shows `dest_path` and frame count. Re-submit with the same options → 409 / "Overwrite" hint appears, tick Overwrite, resubmit → 200.
2. **Server dir, v3-native (regression)**: Format=v3-native, Destination=Save to server, Submit → success.
3. **Zip, VLA-compat (new)**: Format=VLA-compat, Destination=Download as zip, Submit. Browser downloads `<ds>_vla.zip`. Unzip and confirm `meta/info.json`, `data/chunk-000/*.parquet`, `videos/*/chunk-000/*.mp4` are present.
4. **Zip, v3-native (existing path, now reachable from modal)**: Format=v3-native, Destination=Download as zip, Submit. Browser downloads `<ds>.zip`.

- [ ] **Step 3: If any scenario fails, debug and fix**

If a scenario fails:
- For 422 / 400 from the backend, check the route's query-param types match the URL the frontend is building (open browser DevTools → Network tab → request URL).
- For an empty zip, check the tempdir variable is `tmp_root / ds` (the orchestrator writes under `<dest_root>/<dataset_name>`).
- For a tempdir not cleaning up, check the `with TemporaryDirectory()` block ends *before* `yield buf.read()` in `generate_vla()`.

If you fix anything, re-run the affected backend tests and recommit.

---

## Self-Review Notes

**Spec coverage check**:
- §Goals.1 (zip stream of converted tree) → Tasks 1+2.
- §Goals.2 (frontend toggle) → Task 6.
- §Goals.3 (no persistent server-side artifact) → Task 1's tempdir-leak assertion + Task 2 impl uses `with TemporaryDirectory()`.
- §Validation.instruction_template default → Task 5.
- §Validation.invalid robot_type → 422 → Task 4.
- §Validation.ValueError → 400 → Task 2 impl wraps the exporter call (no dedicated test; exercised indirectly when override resolution fails — acceptable: the existing `POST /export` path already covers ValueError translation, and we reuse the same exporter).
- §Tests 1-5 → Tasks 1, 3, 5, 4, plus an implicit regression check in Task 2 Step 4.

**Type consistency**: `download_archive` query param `robot_type: Literal["so101", "rebot"] | None`. Matches `RobotTypeOverride = "so101" | "rebot"` in `frontend/src/api/types.ts:61` and the existing `POST /export` body's allowed values. `DEFAULT_INSTRUCTION_TEMPLATE` matches the constant the schemas module exports (`backend/mimicrec/api/schemas.py:103`).
