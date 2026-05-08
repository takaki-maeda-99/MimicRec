# HF Hub push integration — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MimicRec の LeRobot v3 dataset を Hugging Face Hub の private dataset repo に手動・自動で push できるようにする（spec: `docs/superpowers/specs/2026-05-09-hf-hub-push-design.md`）。

**Architecture:** dataset 配下の writer をすべて atomic 化し、push は hardlink snapshot を切ってから `huggingface_hub.HfApi.upload_large_folder` で送る。`PushCoordinator` が dataset 単位の RLock + in-flight set + 進捗状態を持ち、save / push / tombstone / annotate を排他する。

**Tech Stack:** Python 3.12 / FastAPI / asyncio / `huggingface_hub>=0.34` / pyarrow / React 19 / TanStack Query / pytest / Vite

---

## Test commands

- バックエンド全体: `bash scripts/test.sh tests/ -q`
- 個別ファイル: `bash scripts/test.sh tests/unit/test_atomic_io.py -v`
- 個別関数: `bash scripts/test.sh tests/unit/test_atomic_io.py::test_replace_atomic_text -v`
- API: `bash scripts/test.sh tests/api/ -q`

`bash scripts/test.sh` は `.venv/bin/pytest` を `PYTHONNOUSERSITE=1` で起動し、`PYTHONPATH` を unset する公式ランナー。**直接 `pytest` や `uv run pytest` を呼ばない**こと。

---

## File structure

### 新規ファイル

| Path | Responsibility |
|---|---|
| `backend/mimicrec/recording/atomic_io.py` | `_atomic_write_parquet` / `_atomic_write_text` ヘルパー（tmp + os.replace） |
| `backend/mimicrec/cloud/__init__.py` | パッケージマーカー（空） |
| `backend/mimicrec/cloud/push_state.py` | `PushProgress`, `PushCoordinator`（in_flight set / save_locks / progress dict） |
| `backend/mimicrec/cloud/hub_meta.py` | `HubMeta` dataclass、`read_hub_meta` / `write_hub_meta` / `compute_manifest_hash` |
| `backend/mimicrec/cloud/snapshot.py` | `detect_symlinks` / `make_push_snapshot` / `_strip_tombstoned` / `collect_tombstoned_files` / `cleanup_snapshot` |
| `backend/mimicrec/cloud/hf_pusher.py` | `PushResult`, `push_dataset(snapshot, repo_id, …)`（HfApi 直叩き） |
| `backend/mimicrec/api/routes/cloud.py` | `/api/cloud/auth-status`, `/api/datasets/{ds}/hub*`, `/api/datasets/{ds}/hub/push` |
| `backend/mimicrec/api/util.py` | `safe_dataset_path(root, ds_name)` |
| `tests/unit/test_atomic_io.py` | atomic_io ユニットテスト |
| `tests/unit/test_push_state.py` | PushCoordinator ユニットテスト |
| `tests/unit/test_hub_meta.py` | HubMeta read/write/manifest_hash |
| `tests/unit/test_snapshot.py` | snapshot 作成・symlink 検出・tombstone strip |
| `tests/unit/test_hf_pusher.py` | HfApi モック検証 |
| `tests/api/test_cloud_routes.py` | API エンドポイント |
| `tests/integration/__init__.py` | (既存なら不要) |
| `tests/integration/test_atomic_save.py` | save 中の partial-read |
| `tests/integration/test_auto_push_flow.py` | save → auto-push enqueue |
| `tests/integration/test_snapshot_consistency.py` | hardlink 凍結 / dirty 判定 / tombstone strip |
| `tests/integration/test_tombstone_hub_cleanup.py` | tombstone → 再 push の orphan delete |
| `tests/live/test_hf_live_push.py` | `HF_TOKEN` env 有時のみ実行する live test |
| `frontend/src/api/cloud.ts` | TS API クライアント |

### 修正ファイル

| Path | 変更内容 |
|---|---|
| `backend/pyproject.toml` | `huggingface_hub>=0.34` を `dependencies` に追加 |
| `backend/mimicrec/recording/pending.py` | `save()` を atomic + RLock 取得 + auto-push トリガ。`__init__` に `coordinator` / `ds_name` を追加 |
| `backend/mimicrec/recording/metadata.py` | `append_episode` / `tombstone_episode` / `upsert_task` / `update_info_totals` を atomic + RLock 取得 + `coordinator` / `ds_name` kwargs |
| `backend/mimicrec/recording/dataset_layout.py` | `init_dataset()` を atomic 化 + `mkdir(exist_ok=False)` で TOCTOU 修正 |
| `backend/mimicrec/annotator/subtask.py` | `save_annotations` を atomic + RLock 取得 + `coordinator` / `ds_name` kwargs |
| `backend/mimicrec/api/app.py` | `cloud` ルーター登録 + `app.state.push_coordinator = PushCoordinator()` 初期化 |
| `backend/mimicrec/api/routes/datasets.py` | `DELETE /datasets/{ds}` を coordinator 連携、`POST /datasets` の `FileExistsError → 409`、annotate / tasks / tombstone ルートに coordinator + ds_name を渡す |
| `backend/mimicrec/api/deps.py` | `create_session_from_request` で `coordinator` を `PendingEpisode` に注入できるよう経路追加 |
| `backend/mimicrec/session/lifecycle.py` | `SessionManager` が `coordinator` を保持 / `app_loop` を保持し `PendingEpisode` に渡す |
| `frontend/src/pages/DatasetsPage.tsx` (or `SettingsPage.tsx`) | Hub セクション追加 |

---

## Task ordering rationale

1. 依存追加 → atomic ヘルパー → 既存 writer の atomic 化（既存テストで回帰検出）
2. `cloud/` パッケージのデータ構造（PushCoordinator / HubMeta）→ snapshot → pusher
3. lock 注入で writer に coordinator / ds_name を流す
4. API ルート + DELETE 連携
5. SessionManager 経由で PendingEpisode に coordinator 注入 + auto-push フック
6. Frontend
7. Integration / live テスト
8. 起動時クリーンアップ（孤立 snapshot dir 削除）

---

## Task 1: huggingface_hub を依存に追加

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: dependencies に追加**

`backend/pyproject.toml` の `dependencies = [...]` 末尾に `"huggingface_hub>=0.34"` を 1 行追加:

```toml
dependencies = [
  "pyarrow>=15",
  "numpy>=1.26",
  "omegaconf>=2.3",
  "pydantic>=2.7",
  "opencv-python>=4.9",
  "av>=12",
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "scipy>=1.15.3",
  "open-gopro==0.22.0",
  "huggingface_hub>=0.34",
]
```

- [ ] **Step 2: 依存を再インストール**

```bash
uv pip install --python .venv/bin/python -e "./backend[dev]"
```

期待: `huggingface_hub-0.x.y` が `Successfully installed` の中に出る。

- [ ] **Step 3: import 動作確認**

```bash
.venv/bin/python -c "from huggingface_hub import HfApi; print(HfApi().__class__.__name__)"
```

期待: `HfApi` と表示される。

- [ ] **Step 4: コミット**

```bash
git add backend/pyproject.toml
git commit -m "chore(deps): add huggingface_hub>=0.34 for HF Hub push"
```

---

## Task 2: `recording/atomic_io.py` を作成

**Files:**
- Create: `backend/mimicrec/recording/atomic_io.py`
- Test: `tests/unit/test_atomic_io.py`

- [ ] **Step 1: failing test を書く**

`tests/unit/test_atomic_io.py`:

```python
from __future__ import annotations
import json
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicrec.recording.atomic_io import _atomic_write_parquet, _atomic_write_text


def test_atomic_write_text_creates_file(tmp_path: Path):
    dst = tmp_path / "info.json"
    _atomic_write_text(dst, json.dumps({"k": 1}))
    assert dst.read_text() == json.dumps({"k": 1})


def test_atomic_write_text_overwrites(tmp_path: Path):
    dst = tmp_path / "info.json"
    dst.write_text("old")
    _atomic_write_text(dst, "new")
    assert dst.read_text() == "new"


def test_atomic_write_text_tmp_cleanup_on_error(tmp_path: Path, monkeypatch):
    dst = tmp_path / "info.json"

    real_replace = __import__("os").replace
    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr("os.replace", boom)

    with pytest.raises(RuntimeError):
        _atomic_write_text(dst, "new")
    # tmp file は cleanup されている
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())


def test_atomic_write_parquet_roundtrip(tmp_path: Path):
    dst = tmp_path / "data.parquet"
    table = pa.table({"a": [1, 2, 3]})
    _atomic_write_parquet(table, dst)
    got = pq.read_table(dst)
    assert got.to_pylist() == [{"a": 1}, {"a": 2}, {"a": 3}]


def test_atomic_write_no_partial_visible(tmp_path: Path, monkeypatch):
    """tmp に書き終わるまで dst は古い内容のまま見える"""
    dst = tmp_path / "info.json"
    dst.write_text("old")

    real_replace = __import__("os").replace
    captured_tmp = {}

    def slow_replace(src, target):
        captured_tmp["src"] = src
        # replace 直前に dst を読むと old が見える
        assert dst.read_text() == "old"
        return real_replace(src, target)

    monkeypatch.setattr("os.replace", slow_replace)
    _atomic_write_text(dst, "new")
    assert dst.read_text() == "new"
```

- [ ] **Step 2: テストが fail することを確認**

```bash
bash scripts/test.sh tests/unit/test_atomic_io.py -v
```

期待: ImportError (`No module named 'mimicrec.recording.atomic_io'`) で全件 fail。

- [ ] **Step 3: 最小実装を書く**

`backend/mimicrec/recording/atomic_io.py`:

```python
from __future__ import annotations
import os
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def _atomic_write_text(path: Path, content: str) -> None:
    """Atomically write `content` to `path` via tmp + os.replace.

    The tmp file is created in `path.parent` (so the rename stays within the
    same filesystem) with a unique name and is unlinked on failure.
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _atomic_write_parquet(table: pa.Table, dst: Path) -> None:
    """Atomically write a pyarrow table to `dst` via tmp + os.replace."""
    parent = dst.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=dst.name + ".", suffix=".tmp", dir=parent)
    os.close(fd)   # pq.write_table opens its own handle
    tmp = Path(tmp_name)
    try:
        pq.write_table(table, tmp)
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
```

- [ ] **Step 4: テストが pass することを確認**

```bash
bash scripts/test.sh tests/unit/test_atomic_io.py -v
```

期待: 5 件 pass。

- [ ] **Step 5: コミット**

```bash
git add backend/mimicrec/recording/atomic_io.py tests/unit/test_atomic_io.py
git commit -m "feat(recording): add atomic_io helpers (tmp + os.replace)"
```

---

## Task 3: `recording/metadata.py` の 4 箇所を atomic 化

**Files:**
- Modify: `backend/mimicrec/recording/metadata.py:91, 125, 142, 160`

このタスクでは **lock 注入はまだ行わない**（atomic 化のみ）。lock kwargs は Task 9 で追加する。

- [ ] **Step 1: 既存 metadata roundtrip テストの中身確認**

```bash
bash scripts/test.sh tests/unit/test_metadata_roundtrip.py -v
```

期待: 既存テスト全件 pass。リファクタ後も同じテストが pass することを担保する。

- [ ] **Step 2: 新規 atomicity test を書く**

`tests/unit/test_metadata_atomic.py`:

```python
from __future__ import annotations
import json
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.recording.metadata import (
    append_episode, tombstone_episode, upsert_task, update_info_totals
)


def _init_meta(tmp_path: Path) -> Path:
    meta = tmp_path / "meta"
    meta.mkdir()
    info = {"total_episodes": 0, "total_frames": 0, "total_tasks": 0,
            "fps": 30, "splits": {"train": "0:0"}, "features": {}}
    (meta / "info.json").write_text(json.dumps(info))
    pq.write_table(pa.table({"task": [], "task_index": [], "instruction": []}),
                   meta / "tasks.parquet")
    return meta


def test_append_episode_no_partial_parquet(tmp_path: Path, monkeypatch):
    """append_episode のクラッシュで episodes.parquet が partial にならない."""
    meta = _init_meta(tmp_path)
    append_episode(meta, {"episode_index": 0, "task": "t", "num_frames": 5,
                          "duration_sec": 1.0, "cameras": []})

    # 既存の episodes.parquet を確認
    pq_path = meta / "episodes" / "chunk-000" / "file-000.parquet"
    assert pq_path.exists()

    # 2 回目の append を pq.write_table 直前で例外にする
    real_pq_write = pq.write_table
    call_count = {"n": 0}

    def boom(table, path, *a, **k):
        if "file-000" in str(path):
            call_count["n"] += 1
            if call_count["n"] >= 1:
                raise RuntimeError("simulated crash")
        return real_pq_write(table, path, *a, **k)

    monkeypatch.setattr(pq, "write_table", boom)
    try:
        append_episode(meta, {"episode_index": 1, "task": "t", "num_frames": 3,
                              "duration_sec": 0.5, "cameras": []})
    except RuntimeError:
        pass

    # 元の episodes.parquet が壊れていない（episode_index=0 だけ読める）
    rows = pq.read_table(pq_path).to_pylist()
    assert len(rows) == 1
    assert rows[0]["episode_index"] == 0


def test_update_info_totals_no_partial_json(tmp_path: Path, monkeypatch):
    meta = _init_meta(tmp_path)
    info_path = meta / "info.json"
    original = info_path.read_text()

    real_replace = __import__("os").replace
    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr("os.replace", boom)

    try:
        update_info_totals(meta)
    except RuntimeError:
        pass

    # 旧 info.json が無傷で残っている
    assert info_path.read_text() == original
    # tmp が dir に残っていない
    assert not any(p.name.endswith(".tmp") for p in meta.iterdir())
```

- [ ] **Step 3: テストが fail することを確認**

```bash
bash scripts/test.sh tests/unit/test_metadata_atomic.py -v
```

期待: 現状の `pq.write_table` / `write_text` 直書き実装では partial が見える or tmp 残存で fail。

- [ ] **Step 4: metadata.py を atomic 化**

`backend/mimicrec/recording/metadata.py` を以下のように変更（差分のみ示す）:

ファイル先頭の import 群に追加:
```python
from mimicrec.recording.atomic_io import _atomic_write_parquet, _atomic_write_text
```

`append_episode()` の `pq.write_table(table, pq_path)`（line 91 付近）を:
```python
_atomic_write_parquet(table, pq_path)
```

`tombstone_episode()` の `pq.write_table(pa.Table.from_pylist(rows), pq_path)`（line 125 付近）を:
```python
_atomic_write_parquet(pa.Table.from_pylist(rows), pq_path)
```

`upsert_task()` の `pq.write_table(pa.Table.from_pylist(tasks), pq_path)`（line 142 付近）を:
```python
_atomic_write_parquet(pa.Table.from_pylist(tasks), pq_path)
```

`update_info_totals()` の `info_path.write_text(json.dumps(info, indent=2))`（line 160 付近）を:
```python
_atomic_write_text(info_path, json.dumps(info, indent=2))
```

- [ ] **Step 5: 新規テスト pass**

```bash
bash scripts/test.sh tests/unit/test_metadata_atomic.py -v
```

期待: 2 件 pass。

- [ ] **Step 6: 既存テストの回帰なしを確認**

```bash
bash scripts/test.sh tests/unit/test_metadata_roundtrip.py tests/unit/test_dataset_reader_tombstones.py tests/unit/test_recording_info_json.py -v
```

期待: 既存件数すべて pass。

- [ ] **Step 7: コミット**

```bash
git add backend/mimicrec/recording/metadata.py tests/unit/test_metadata_atomic.py
git commit -m "refactor(recording): make metadata.py writers atomic"
```

---

## Task 4: `recording/pending.py` の data parquet 書き出しを atomic 化

**Files:**
- Modify: `backend/mimicrec/recording/pending.py:113`

- [ ] **Step 1: failing test**

`tests/unit/test_pending_atomic.py`:

```python
from __future__ import annotations
from pathlib import Path
import pyarrow.parquet as pq
import pytest

from mimicrec.recording.pending import PendingEpisode
from mimicrec.recording.dataset_layout import init_dataset


def _init_dataset(root: Path) -> Path:
    init_dataset(root, fps=30, joint_names=["j0"], camera_names=[])
    return root


def test_save_no_partial_data_parquet(tmp_path: Path, monkeypatch):
    ds = _init_dataset(tmp_path / "ds")
    ep = PendingEpisode.open(ds, episode_index=0)
    ep.append_row({"action": [0.1], "observation.state": [0.0], "timestamp": 0.0,
                   "frame_index": 0, "episode_index": 0, "index": 0, "task_index": 0})
    ep.finalize()

    # save 中で os.replace が失敗する状況を作る
    real_replace = __import__("os").replace
    def boom(src, target):
        if str(target).endswith(".parquet") and "data/chunk" in str(target):
            raise RuntimeError("disk full")
        return real_replace(src, target)
    monkeypatch.setattr("os.replace", boom)

    with pytest.raises(RuntimeError):
        ep.save({"episode_index": 0, "task": "t", "num_frames": 1,
                 "duration_sec": 0.0, "cameras": [], "fps": 30})

    # data/chunk-000/episode_000000.parquet が **存在しない**（半端ファイルなし）
    dst = ds / "data" / "chunk-000" / "episode_000000.parquet"
    assert not dst.exists()
    # tmp ファイルも残っていない
    assert not any(p.name.endswith(".tmp")
                   for p in (ds / "data" / "chunk-000").iterdir() if (ds / "data" / "chunk-000").exists())
```

- [ ] **Step 2: テストが fail することを確認**

```bash
bash scripts/test.sh tests/unit/test_pending_atomic.py -v
```

期待: 現状 `pq.write_table(table, dst)` が直接 dst を作るので partial parquet が残り fail。

- [ ] **Step 3: pending.py を atomic 化**

`backend/mimicrec/recording/pending.py` の `save()` 内、line 113 付近:

変更前:
```python
        table = pq.read_table(src)
        n = table.num_rows
        timestamps = pa.array([i / fps for i in range(n)], type=pa.float32())
        indices = pa.array([dataset_from_index + i for i in range(n)], type=pa.int64())
        table = table.set_column(
            table.schema.get_field_index("timestamp"), "timestamp", timestamps,
        )
        table = table.set_column(
            table.schema.get_field_index("index"), "index", indices,
        )
        pq.write_table(table, dst)
        src.unlink()
```

変更後:
```python
        table = pq.read_table(src)
        n = table.num_rows
        timestamps = pa.array([i / fps for i in range(n)], type=pa.float32())
        indices = pa.array([dataset_from_index + i for i in range(n)], type=pa.int64())
        table = table.set_column(
            table.schema.get_field_index("timestamp"), "timestamp", timestamps,
        )
        table = table.set_column(
            table.schema.get_field_index("index"), "index", indices,
        )
        from mimicrec.recording.atomic_io import _atomic_write_parquet
        _atomic_write_parquet(table, dst)
        src.unlink()
```

- [ ] **Step 4: テストが pass する**

```bash
bash scripts/test.sh tests/unit/test_pending_atomic.py tests/unit/test_pending_episode.py -v
```

期待: 全件 pass。

- [ ] **Step 5: コミット**

```bash
git add backend/mimicrec/recording/pending.py tests/unit/test_pending_atomic.py
git commit -m "refactor(recording): atomic write for episode data parquet in PendingEpisode.save()"
```

---

## Task 5: `recording/dataset_layout.py` を atomic 化 + TOCTOU 修正

**Files:**
- Modify: `backend/mimicrec/recording/dataset_layout.py:107, 117`

- [ ] **Step 1: failing test**

`tests/unit/test_init_dataset.py`:

```python
from __future__ import annotations
from pathlib import Path
import pyarrow.parquet as pq
import pytest

from mimicrec.recording.dataset_layout import init_dataset


def test_init_dataset_creates_atomic(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j0"], camera_names=[])
    assert (ds / "meta" / "info.json").exists()
    assert (ds / "meta" / "tasks.parquet").exists()
    # tmp ファイルが残っていない
    assert not any(p.name.endswith(".tmp") for p in (ds / "meta").iterdir())


def test_init_dataset_fails_when_root_exists(tmp_path: Path):
    ds = tmp_path / "ds"
    ds.mkdir()
    with pytest.raises(FileExistsError):
        init_dataset(ds, fps=30, joint_names=["j0"], camera_names=[])
```

- [ ] **Step 2: テストが fail する**

```bash
bash scripts/test.sh tests/unit/test_init_dataset.py -v
```

期待: 2 件目が `mkdir(exist_ok=True)` なので fail（FileExistsError が上がらない）。

- [ ] **Step 3: dataset_layout.py を変更**

`backend/mimicrec/recording/dataset_layout.py`:

冒頭 import 追加:
```python
from mimicrec.recording.atomic_io import _atomic_write_parquet, _atomic_write_text
```

`init_dataset()` の 1 行目を変更（既存の `p.meta_dir.mkdir(...)` 群の前に挿入）:

変更前:
```python
def init_dataset(
    ds_root: Path,
    fps: int,
    ...
) -> None:
    p = dataset_paths(ds_root)
    p.meta_dir.mkdir(parents=True, exist_ok=True)
    p.data_dir.mkdir(parents=True, exist_ok=True)
    ...
```

変更後:
```python
def init_dataset(
    ds_root: Path,
    fps: int,
    ...
) -> None:
    # TOCTOU 防止: ds_root 自体は exist_ok=False で作る（既存なら FileExistsError）
    ds_root.mkdir(parents=True, exist_ok=False)
    p = dataset_paths(ds_root)
    p.meta_dir.mkdir(parents=True, exist_ok=True)
    p.data_dir.mkdir(parents=True, exist_ok=True)
    ...
```

line 107 付近の `(p.meta_dir / "info.json").write_text(json.dumps(info, indent=2))` を:
```python
_atomic_write_text(p.meta_dir / "info.json", json.dumps(info, indent=2))
```

line 117 付近の `pq.write_table(pa.table({"task": [], ...}, schema=schema), p.tasks_parquet)` を:
```python
_atomic_write_parquet(pa.table({"task": [], "task_index": [], "instruction": []}, schema=schema), p.tasks_parquet)
```

- [ ] **Step 4: 既存呼び出し元の `if exists` チェックがあるか確認**

```bash
grep -n "ds_root.exists\|init_dataset" backend/mimicrec/api/routes/datasets.py backend/mimicrec/api/deps.py
```

期待: `routes/datasets.py:69` の `if ds_root.exists(): raise ValueError(...)` と `deps.py:142` の `if not ds_root.exists():` がヒット。前者は事前チェックなので OK だが、init_dataset 側の `mkdir(exist_ok=False)` が race を防ぐ二重保護。

- [ ] **Step 5: `routes/datasets.py:67` の `POST /datasets` で `FileExistsError → 409` にマップ**

`backend/mimicrec/api/routes/datasets.py` の `create_dataset()`:

変更前:
```python
@router.post("/datasets")
async def create_dataset(request: Request, body: CreateDatasetRequest):
    root = get_datasets_root(request.app)
    ds_root = root / body.name
    if ds_root.exists():
        raise ValueError(f"dataset '{body.name}' already exists")
    ...
    init_dataset(ds_root, ...)
```

変更後:
```python
@router.post("/datasets")
async def create_dataset(request: Request, body: CreateDatasetRequest):
    root = get_datasets_root(request.app)
    ds_root = root / body.name
    if ds_root.exists():
        raise HTTPException(status_code=409, detail=f"dataset '{body.name}' already exists")
    ...
    try:
        init_dataset(ds_root, ...)
    except FileExistsError:
        # race: 別リクエストが直前に作った
        raise HTTPException(status_code=409, detail=f"dataset '{body.name}' already exists")
```

- [ ] **Step 6: テスト pass**

```bash
bash scripts/test.sh tests/unit/test_init_dataset.py tests/unit/test_recording_info_json.py tests/api/test_dataset_routes.py -v
```

期待: 全件 pass。

- [ ] **Step 7: コミット**

```bash
git add backend/mimicrec/recording/dataset_layout.py backend/mimicrec/api/routes/datasets.py tests/unit/test_init_dataset.py
git commit -m "refactor(recording): atomic init_dataset + mkdir(exist_ok=False) TOCTOU fix"
```

---

## Task 6: `annotator/subtask.py:254` を atomic 化

**Files:**
- Modify: `backend/mimicrec/annotator/subtask.py:254`

- [ ] **Step 1: ファイル該当箇所の文脈把握**

```bash
sed -n '245,260p' backend/mimicrec/annotator/subtask.py
```

期待: `pq.write_table(new_table, pq_path)` が表示される（`pq_path` は **episode data parquet**、subtasks 専用ではない点注意）。

- [ ] **Step 2: failing test**

`tests/unit/test_subtask_atomic.py`:

```python
from __future__ import annotations
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicrec.annotator.subtask import save_annotations, SubtaskSegment


def _make_episode_parquet(tmp_path: Path) -> Path:
    ds = tmp_path / "ds"
    chunk = ds / "data" / "chunk-000"
    chunk.mkdir(parents=True)
    pq_path = chunk / "episode_000000.parquet"
    table = pa.table({
        "frame_index": list(range(10)),
        "episode_index": [0] * 10,
        "action": [[0.0]] * 10,
    })
    pq.write_table(table, pq_path)
    (ds / "meta" / "episodes" / "chunk-000").mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"episode_index": [0]}),
                   ds / "meta" / "episodes" / "chunk-000" / "file-000.parquet")
    return ds


def test_save_annotations_no_partial(tmp_path: Path, monkeypatch):
    ds = _make_episode_parquet(tmp_path)
    pq_path = ds / "data" / "chunk-000" / "episode_000000.parquet"
    original_bytes = pq_path.read_bytes()

    real_replace = __import__("os").replace
    def boom(src, target):
        if str(target).endswith("episode_000000.parquet"):
            raise RuntimeError("disk full")
        return real_replace(src, target)
    monkeypatch.setattr("os.replace", boom)

    segments = [SubtaskSegment(name="grasp", start_frame=0, end_frame=4, description="x")]
    with pytest.raises(RuntimeError):
        save_annotations(ds, episode_index=0, segments=segments)

    # 元 parquet が無傷
    assert pq_path.read_bytes() == original_bytes
```

- [ ] **Step 3: fail を確認**

```bash
bash scripts/test.sh tests/unit/test_subtask_atomic.py -v
```

期待: fail（`pq.write_table` 直書きが原本を上書きしてしまう）。

- [ ] **Step 4: subtask.py を変更**

`backend/mimicrec/annotator/subtask.py:254` 周辺を atomic 化:

変更前:
```python
    import pyarrow as pa
    new_table = pa.Table.from_pylist(rows)
    pq.write_table(new_table, pq_path)
    logger.info(f"Saved {len(segments)} subtask annotations to {pq_path}")
```

変更後:
```python
    import pyarrow as pa
    from mimicrec.recording.atomic_io import _atomic_write_parquet
    new_table = pa.Table.from_pylist(rows)
    _atomic_write_parquet(new_table, pq_path)
    logger.info(f"Saved {len(segments)} subtask annotations to {pq_path}")
```

- [ ] **Step 5: pass 確認**

```bash
bash scripts/test.sh tests/unit/test_subtask_atomic.py -v
```

期待: pass。

- [ ] **Step 6: コミット**

```bash
git add backend/mimicrec/annotator/subtask.py tests/unit/test_subtask_atomic.py
git commit -m "refactor(annotator): atomic write for save_annotations"
```

---

## Task 7: `cloud/__init__.py` + `cloud/push_state.py` を作成

**Files:**
- Create: `backend/mimicrec/cloud/__init__.py`
- Create: `backend/mimicrec/cloud/push_state.py`
- Test: `tests/unit/test_push_state.py`

- [ ] **Step 1: failing test**

`tests/unit/test_push_state.py`:

```python
from __future__ import annotations
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from mimicrec.cloud.push_state import PushCoordinator, PushProgress


def test_progress_default():
    p = PushProgress()
    assert p.status == "idle"
    assert p.error is None


def test_try_reserve_returns_true_first():
    c = PushCoordinator()
    assert c.try_reserve("ds_a") is True
    assert c.try_reserve("ds_a") is False
    c.release("ds_a")
    assert c.try_reserve("ds_a") is True


def test_try_reserve_concurrent_only_one_wins():
    c = PushCoordinator()
    results: list[bool] = []
    barrier = threading.Barrier(20)

    def worker():
        barrier.wait()
        results.append(c.try_reserve("ds_a"))

    with ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(lambda _: worker(), range(20)))

    assert results.count(True) == 1
    assert results.count(False) == 19


def test_get_save_lock_is_rlock():
    c = PushCoordinator()
    lock = c.get_save_lock("ds_a")
    # RLock: same thread can acquire twice
    assert lock.acquire(timeout=1)
    try:
        assert lock.acquire(timeout=1)
        lock.release()
    finally:
        lock.release()


def test_get_save_lock_returns_same_instance():
    c = PushCoordinator()
    a = c.get_save_lock("ds_a")
    b = c.get_save_lock("ds_a")
    assert a is b


def test_drop_dataset_clears_state():
    c = PushCoordinator()
    c.try_reserve("ds_a")
    c.get_save_lock("ds_a")
    c.progress["ds_a"] = PushProgress(status="done")
    c.drop_dataset("ds_a")
    assert "ds_a" not in c.in_flight
    assert "ds_a" not in c.save_locks
    assert "ds_a" not in c.progress
```

- [ ] **Step 2: fail 確認**

```bash
bash scripts/test.sh tests/unit/test_push_state.py -v
```

期待: ImportError (`No module named 'mimicrec.cloud'`)。

- [ ] **Step 3: 実装**

`backend/mimicrec/cloud/__init__.py`:
```python
```
（空ファイル）

`backend/mimicrec/cloud/push_state.py`:

```python
from __future__ import annotations
import threading
from dataclasses import dataclass
from typing import Literal


@dataclass
class PushProgress:
    status: Literal["idle", "queued", "uploading", "done", "error"] = "idle"
    started_at: str | None = None
    ended_at: str | None = None
    error: str | None = None
    repo_id: str | None = None
    last_pushed_commit_sha: str | None = None


class PushCoordinator:
    """Per-process state for HF push tasks. Single-process / single-event-loop only."""

    def __init__(self) -> None:
        self._mu = threading.Lock()
        self.in_flight: set[str] = set()
        self.save_locks: dict[str, threading.RLock] = {}
        self.progress: dict[str, PushProgress] = {}

    def try_reserve(self, ds_name: str) -> bool:
        """Atomically check & reserve. Returns True if reserved, False if already in-flight."""
        with self._mu:
            if ds_name in self.in_flight:
                return False
            self.in_flight.add(ds_name)
            return True

    def release(self, ds_name: str) -> None:
        with self._mu:
            self.in_flight.discard(ds_name)

    def get_save_lock(self, ds_name: str) -> threading.RLock:
        """RLock so that nested writer calls (append_episode → update_info_totals)
        on the same thread don't deadlock."""
        with self._mu:
            existing = self.save_locks.get(ds_name)
            if existing is None:
                existing = threading.RLock()
                self.save_locks[ds_name] = existing
            return existing

    def drop_dataset(self, ds_name: str) -> None:
        """Cleanup all state for a deleted dataset."""
        with self._mu:
            self.in_flight.discard(ds_name)
            self.save_locks.pop(ds_name, None)
            self.progress.pop(ds_name, None)
```

- [ ] **Step 4: pass 確認**

```bash
bash scripts/test.sh tests/unit/test_push_state.py -v
```

期待: 6 件 pass。

- [ ] **Step 5: コミット**

```bash
git add backend/mimicrec/cloud/__init__.py backend/mimicrec/cloud/push_state.py tests/unit/test_push_state.py
git commit -m "feat(cloud): PushCoordinator with in-flight set and per-dataset RLock"
```

---

## Task 8: `cloud/hub_meta.py` — HubMeta + manifest hash

**Files:**
- Create: `backend/mimicrec/cloud/hub_meta.py`
- Test: `tests/unit/test_hub_meta.py`

- [ ] **Step 1: failing test**

`tests/unit/test_hub_meta.py`:

```python
from __future__ import annotations
import os
import time
from pathlib import Path

from mimicrec.cloud.hub_meta import (
    HubMeta, read_hub_meta, write_hub_meta, compute_manifest_hash, hub_meta_path,
)


def _mkds(tmp_path: Path) -> Path:
    ds = tmp_path / "ds"
    (ds / "meta").mkdir(parents=True)
    (ds / "data" / "chunk-000").mkdir(parents=True)
    (ds / "videos").mkdir()
    return ds


def test_read_hub_meta_returns_none_when_absent(tmp_path: Path):
    ds = _mkds(tmp_path)
    assert read_hub_meta(ds) is None


def test_write_then_read_roundtrip(tmp_path: Path):
    ds = _mkds(tmp_path)
    meta = HubMeta(repo_id="user/dataset", private=True, auto_push=True)
    write_hub_meta(ds, meta)
    got = read_hub_meta(ds)
    assert got == meta


def test_write_is_atomic(tmp_path: Path, monkeypatch):
    ds = _mkds(tmp_path)
    write_hub_meta(ds, HubMeta(repo_id="u/d"))
    original = hub_meta_path(ds).read_text()

    real_replace = __import__("os").replace
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr("os.replace", boom)

    try:
        write_hub_meta(ds, HubMeta(repo_id="u/d", auto_push=True))
    except RuntimeError:
        pass
    assert hub_meta_path(ds).read_text() == original


def test_default_private_is_true(tmp_path: Path):
    meta = HubMeta(repo_id="u/d")
    assert meta.private is True
    assert meta.auto_push is False


def test_compute_manifest_hash_excludes_pending_and_hub(tmp_path: Path):
    ds = _mkds(tmp_path)
    (ds / "data" / "chunk-000" / "episode_000000.parquet").write_bytes(b"a")
    (ds / "meta" / "info.json").write_text("{}")
    h1 = compute_manifest_hash(ds)

    # pending と hub.json は ignore されるべき
    (ds / ".pending").mkdir()
    (ds / ".pending" / "tmp.parquet").write_bytes(b"x")
    write_hub_meta(ds, HubMeta(repo_id="u/d"))
    h2 = compute_manifest_hash(ds)
    assert h1 == h2


def test_manifest_hash_changes_on_size_change(tmp_path: Path):
    ds = _mkds(tmp_path)
    f = ds / "data" / "chunk-000" / "episode_000000.parquet"
    f.write_bytes(b"abc")
    h1 = compute_manifest_hash(ds)

    # mtime も変わるが size も変わる
    f.write_bytes(b"abcd")
    h2 = compute_manifest_hash(ds)
    assert h1 != h2


def test_manifest_hash_changes_on_mtime_only_change(tmp_path: Path):
    ds = _mkds(tmp_path)
    f = ds / "data" / "chunk-000" / "episode_000000.parquet"
    f.write_bytes(b"abc")
    h1 = compute_manifest_hash(ds)

    # 同サイズで mtime だけ変える（実装は path+size+mtime_ns)
    new_mtime = time.time() + 10
    os.utime(f, (new_mtime, new_mtime))
    h2 = compute_manifest_hash(ds)
    assert h1 != h2
```

- [ ] **Step 2: fail 確認**

```bash
bash scripts/test.sh tests/unit/test_hub_meta.py -v
```

期待: ImportError。

- [ ] **Step 3: 実装**

`backend/mimicrec/cloud/hub_meta.py`:

```python
from __future__ import annotations
import hashlib
import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from mimicrec.recording.atomic_io import _atomic_write_text


@dataclass
class HubMeta:
    repo_id: str
    private: bool = True
    auto_push: bool = False
    last_pushed_at: str | None = None
    last_pushed_commit_sha: str | None = None
    last_pushed_manifest_hash: str | None = None
    last_push_error: str | None = None


def hub_meta_path(ds_root: Path) -> Path:
    return ds_root / "meta" / "hub.json"


def read_hub_meta(ds_root: Path) -> HubMeta | None:
    p = hub_meta_path(ds_root)
    if not p.exists():
        return None
    raw = json.loads(p.read_text())
    # 未知 key は無視（forward-compat）
    known = {f.name for f in fields(HubMeta)}
    return HubMeta(**{k: v for k, v in raw.items() if k in known})


def write_hub_meta(ds_root: Path, meta: HubMeta) -> None:
    _atomic_write_text(hub_meta_path(ds_root), json.dumps(asdict(meta), indent=2))


# Manifest hash で除外するパス（snapshot ignore と同集合 + meta/hub.json 自身）
_MANIFEST_IGNORE_DIRS = {".pending", ".cache", ".git"}
_MANIFEST_IGNORE_FILES = {"meta/hub.json"}


def compute_manifest_hash(ds_root: Path) -> str:
    """sha256 of sorted (relative_path, size, mtime_ns) tuples for push-target files."""
    entries: list[tuple[str, int, int]] = []
    root = ds_root.resolve()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        rel_str = rel.as_posix()
        # ignore: 任意 segment が _MANIFEST_IGNORE_DIRS に含まれる、
        # または full relative path が _MANIFEST_IGNORE_FILES に該当
        if any(part in _MANIFEST_IGNORE_DIRS for part in rel.parts):
            continue
        if rel_str in _MANIFEST_IGNORE_FILES:
            continue
        st = path.stat()
        entries.append((rel_str, st.st_size, st.st_mtime_ns))
    entries.sort()
    h = hashlib.sha256()
    for rel_str, size, mtime_ns in entries:
        h.update(f"{rel_str}\0{size}\0{mtime_ns}\n".encode())
    return f"sha256:{h.hexdigest()}"
```

- [ ] **Step 4: pass 確認**

```bash
bash scripts/test.sh tests/unit/test_hub_meta.py -v
```

期待: 7 件 pass。

- [ ] **Step 5: コミット**

```bash
git add backend/mimicrec/cloud/hub_meta.py tests/unit/test_hub_meta.py
git commit -m "feat(cloud): HubMeta dataclass + atomic read/write + manifest hash"
```

---

## Task 9: writer 関数群に `coordinator` / `ds_name` kwargs を導入

**Files:**
- Modify: `backend/mimicrec/recording/metadata.py`
- Modify: `backend/mimicrec/annotator/subtask.py`

呼び出し元（routes / pending / session）への波及は次タスクで行う。ここでは **書き込み関数自身が lock を取る** ようにする。引数は **後方互換** で `coordinator: PushCoordinator | None = None`、`ds_name: str | None = None` をデフォルト None に。両方与えられた場合のみ lock 取得。

- [ ] **Step 1: lock 取得テストを書く**

`tests/unit/test_metadata_lock.py`:

```python
from __future__ import annotations
import threading
import time
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.cloud.push_state import PushCoordinator
from mimicrec.recording.metadata import append_episode, update_info_totals
from mimicrec.recording.dataset_layout import init_dataset


def test_append_episode_acquires_save_lock(tmp_path: Path):
    init_dataset(tmp_path / "ds", fps=30, joint_names=["j0"], camera_names=[])
    ds = tmp_path / "ds"
    coord = PushCoordinator()
    save_lock = coord.get_save_lock("ds")

    # 別 thread で lock を握っておくと append_episode が待たされる
    holder_released = threading.Event()
    started = threading.Event()
    completed = threading.Event()

    def hold():
        with save_lock:
            started.set()
            holder_released.wait(timeout=2.0)

    def caller():
        append_episode(
            ds / "meta",
            {"episode_index": 0, "task": "t", "num_frames": 1, "duration_sec": 0.1, "cameras": []},
            coordinator=coord, ds_name="ds",
        )
        completed.set()

    t1 = threading.Thread(target=hold)
    t1.start()
    started.wait(timeout=1.0)
    t2 = threading.Thread(target=caller)
    t2.start()
    # caller は lock 待ちで完了しない
    assert not completed.wait(timeout=0.3)
    holder_released.set()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)
    assert completed.is_set()


def test_append_episode_without_coordinator_works(tmp_path: Path):
    """後方互換: coordinator/ds_name を渡さなくても動く"""
    init_dataset(tmp_path / "ds", fps=30, joint_names=["j0"], camera_names=[])
    ds = tmp_path / "ds"
    append_episode(
        ds / "meta",
        {"episode_index": 0, "task": "t", "num_frames": 1, "duration_sec": 0.1, "cameras": []},
    )
    # 例外なく動けば OK
    rows = pq.read_table(ds / "meta" / "episodes" / "chunk-000" / "file-000.parquet").to_pylist()
    assert len(rows) == 1


def test_nested_call_under_rlock_no_deadlock(tmp_path: Path):
    """append_episode が内部で update_info_totals を呼んでも RLock で deadlock しない"""
    init_dataset(tmp_path / "ds", fps=30, joint_names=["j0"], camera_names=[])
    ds = tmp_path / "ds"
    coord = PushCoordinator()
    append_episode(
        ds / "meta",
        {"episode_index": 0, "task": "t", "num_frames": 1, "duration_sec": 0.1, "cameras": []},
        coordinator=coord, ds_name="ds",
    )
    # 内部の update_info_totals も同じ RLock を取るが、再入で通る
```

- [ ] **Step 2: fail 確認**

```bash
bash scripts/test.sh tests/unit/test_metadata_lock.py -v
```

期待: TypeError or fail（kwargs 未対応）。

- [ ] **Step 3: metadata.py に kwargs を追加**

`backend/mimicrec/recording/metadata.py`:

ファイル冒頭に追加:
```python
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mimicrec.cloud.push_state import PushCoordinator


@contextmanager
def _maybe_lock(coordinator, ds_name):
    if coordinator is not None and ds_name is not None:
        lock = coordinator.get_save_lock(ds_name)
        with lock:
            yield
    else:
        yield
```

各関数のシグネチャを変更:

```python
def append_episode(
    meta_dir: Path,
    row: dict,
    *,
    coordinator: "PushCoordinator | None" = None,
    ds_name: str | None = None,
) -> None:
    with _maybe_lock(coordinator, ds_name):
        # 既存ロジックそのまま
        pq_path = _episodes_parquet(meta_dir)
        ...
        _atomic_write_parquet(table, pq_path)
        update_info_totals(meta_dir, coordinator=coordinator, ds_name=ds_name)


def tombstone_episode(
    meta_dir: Path,
    episode_index: int,
    deleted_at_unix: int,
    *,
    coordinator: "PushCoordinator | None" = None,
    ds_name: str | None = None,
) -> None:
    with _maybe_lock(coordinator, ds_name):
        # 既存ロジック
        ...
        _atomic_write_parquet(pa.Table.from_pylist(rows), pq_path)
        update_info_totals(meta_dir, coordinator=coordinator, ds_name=ds_name)


def upsert_task(
    meta_dir: Path,
    task_name: str,
    instruction: str,
    *,
    coordinator: "PushCoordinator | None" = None,
    ds_name: str | None = None,
) -> None:
    with _maybe_lock(coordinator, ds_name):
        # 既存ロジック
        ...
        _atomic_write_parquet(pa.Table.from_pylist(tasks), pq_path)


def update_info_totals(
    meta_dir: Path,
    *,
    coordinator: "PushCoordinator | None" = None,
    ds_name: str | None = None,
) -> None:
    with _maybe_lock(coordinator, ds_name):
        # 既存ロジック
        ...
        _atomic_write_text(info_path, json.dumps(info, indent=2))
```

- [ ] **Step 4: subtask.py に kwargs を追加**

`backend/mimicrec/annotator/subtask.py` の `save_annotations` 関数（line ~230 付近）:

冒頭で `_maybe_lock` 等の import:
```python
from typing import TYPE_CHECKING
from contextlib import contextmanager

if TYPE_CHECKING:
    from mimicrec.cloud.push_state import PushCoordinator
```

シグネチャ:
```python
def save_annotations(
    ds_root: Path,
    episode_index: int,
    segments: list[SubtaskSegment],
    *,
    coordinator: "PushCoordinator | None" = None,
    ds_name: str | None = None,
) -> None:
    if coordinator is not None and ds_name is not None:
        lock = coordinator.get_save_lock(ds_name)
        with lock:
            _save_annotations_inner(ds_root, episode_index, segments)
    else:
        _save_annotations_inner(ds_root, episode_index, segments)


def _save_annotations_inner(ds_root, episode_index, segments):
    # 既存の save_annotations 本体（pq.write_table → _atomic_write_parquet 化済み）
    ...
```

- [ ] **Step 5: pass 確認**

```bash
bash scripts/test.sh tests/unit/test_metadata_lock.py tests/unit/test_metadata_atomic.py tests/unit/test_metadata_roundtrip.py -v
```

期待: 全件 pass。

- [ ] **Step 6: コミット**

```bash
git add backend/mimicrec/recording/metadata.py backend/mimicrec/annotator/subtask.py tests/unit/test_metadata_lock.py
git commit -m "refactor(recording,annotator): add coordinator/ds_name kwargs to writer functions"
```

---

## Task 10: `cloud/snapshot.py` — hardlink + tombstone strip

**Files:**
- Create: `backend/mimicrec/cloud/snapshot.py`
- Test: `tests/unit/test_snapshot.py`

- [ ] **Step 1: failing test**

`tests/unit/test_snapshot.py`:

```python
from __future__ import annotations
import json
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicrec.cloud.snapshot import (
    detect_symlinks, make_push_snapshot, cleanup_snapshot,
    collect_tombstoned_files, SnapshotError,
)
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.metadata import append_episode, tombstone_episode


def _seed_dataset(tmp_path: Path, n_eps: int = 2) -> Path:
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j0"], camera_names=["front"])
    for i in range(n_eps):
        # data parquet
        pq.write_table(
            pa.table({"frame_index": [0], "episode_index": [i],
                      "action": [[0.0]], "observation.state": [[0.0]],
                      "timestamp": [0.0], "index": [i], "task_index": [0]}),
            ds / "data" / "chunk-000" / f"episode_{i:06d}.parquet",
        )
        # mp4 stub
        (ds / "videos" / "observation.images.front" / "chunk-000").mkdir(parents=True, exist_ok=True)
        (ds / "videos" / "observation.images.front" / "chunk-000" / f"episode_{i:06d}.mp4").write_bytes(b"\x00\x00")
        append_episode(
            ds / "meta",
            {"episode_index": i, "task": "t", "num_frames": 1,
             "duration_sec": 0.1, "cameras": ["front"]},
        )
    return ds


def test_make_snapshot_creates_hardlinks(tmp_path: Path):
    ds = _seed_dataset(tmp_path)
    snap = make_push_snapshot(ds)
    try:
        info_orig = (ds / "meta" / "info.json").stat()
        info_snap = (snap / "meta" / "info.json").stat()
        # hardlink: 同 inode、refcount >= 2
        assert info_orig.st_ino == info_snap.st_ino
        assert info_orig.st_nlink >= 2

        ep_orig = (ds / "data" / "chunk-000" / "episode_000000.parquet").stat()
        ep_snap = (snap / "data" / "chunk-000" / "episode_000000.parquet").stat()
        assert ep_orig.st_ino == ep_snap.st_ino
    finally:
        cleanup_snapshot(snap)


def test_snapshot_excludes_pending(tmp_path: Path):
    ds = _seed_dataset(tmp_path)
    pending_file = ds / ".pending" / "tmp.parquet"
    pending_file.parent.mkdir(parents=True, exist_ok=True)
    pending_file.write_bytes(b"x")
    snap = make_push_snapshot(ds)
    try:
        assert not (snap / ".pending").exists()
    finally:
        cleanup_snapshot(snap)


def test_snapshot_fails_on_symlink(tmp_path: Path):
    ds = _seed_dataset(tmp_path)
    target = tmp_path / "external.txt"
    target.write_text("x")
    (ds / "meta" / "evil.txt").symlink_to(target)
    with pytest.raises(SnapshotError):
        make_push_snapshot(ds)


def test_snapshot_strips_tombstoned_episode(tmp_path: Path):
    ds = _seed_dataset(tmp_path, n_eps=2)
    # episode 0 を tombstone
    tombstone_episode(ds / "meta", episode_index=0, deleted_at_unix=1234567890)

    snap = make_push_snapshot(ds)
    try:
        # snapshot から episode_000000 が消えている
        assert not (snap / "data" / "chunk-000" / "episode_000000.parquet").exists()
        assert not (snap / "videos" / "observation.images.front" / "chunk-000" / "episode_000000.mp4").exists()
        # episode_000001 は残っている
        assert (snap / "data" / "chunk-000" / "episode_000001.parquet").exists()
        # episodes.parquet に deleted row が無い
        rows = pq.read_table(snap / "meta" / "episodes" / "chunk-000" / "file-000.parquet").to_pylist()
        assert all(not r.get("deleted") for r in rows)
        assert len(rows) == 1
        # info.json totals が再計算されている
        info = json.loads((snap / "meta" / "info.json").read_text())
        assert info["total_episodes"] == 1
    finally:
        cleanup_snapshot(snap)


def test_cleanup_snapshot_only_removes_marked_dirs(tmp_path: Path):
    other = tmp_path / "not-a-snapshot"
    other.mkdir()
    cleanup_snapshot(other)   # 名前が一致しないので no-op
    assert other.exists()


def test_collect_tombstoned_files_returns_hub_paths(tmp_path: Path):
    ds = _seed_dataset(tmp_path, n_eps=2)
    tombstone_episode(ds / "meta", episode_index=0, deleted_at_unix=1234567890)
    files = collect_tombstoned_files(ds)
    assert "data/chunk-000/episode_000000.parquet" in files
    assert "videos/observation.images.front/chunk-000/episode_000000.mp4" in files


def test_detect_symlinks_skips_ignored_dirs(tmp_path: Path):
    ds = _seed_dataset(tmp_path)
    # .pending 内の symlink は無視される
    pending = ds / ".pending"
    pending.mkdir(exist_ok=True)
    target = tmp_path / "external.txt"
    target.write_text("x")
    (pending / "link").symlink_to(target)
    syms = detect_symlinks(ds)
    assert syms == []
```

- [ ] **Step 2: fail 確認**

```bash
bash scripts/test.sh tests/unit/test_snapshot.py -v
```

期待: ImportError。

- [ ] **Step 3: 実装**

`backend/mimicrec/cloud/snapshot.py`:

```python
from __future__ import annotations
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.recording.atomic_io import _atomic_write_parquet, _atomic_write_text
from mimicrec.recording.metadata import read_episodes


SNAPSHOT_IGNORE = (".pending", ".cache", ".git")


class SnapshotError(RuntimeError):
    pass


def detect_symlinks(ds_root: Path) -> list[Path]:
    """Recursively find symlinks under ds_root, skipping SNAPSHOT_IGNORE dirs."""
    found: list[Path] = []
    for p in ds_root.rglob("*"):
        if not p.is_symlink():
            continue
        rel = p.relative_to(ds_root)
        if any(part in SNAPSHOT_IGNORE for part in rel.parts):
            continue
        found.append(p)
    return found


def make_push_snapshot(ds_root: Path) -> Path:
    """Hardlink-copy ds_root to a sibling dir, then strip tombstoned episodes.
    Caller MUST hold the save_lock for ds_root.name during this call.
    """
    syms = detect_symlinks(ds_root)
    if syms:
        raise SnapshotError(
            f"dataset contains symlinks (forbidden in v1): {syms}"
        )
    snapshot = ds_root.parent / f".push-snapshot-{ds_root.name}-{uuid4().hex[:8]}"

    def _ignore(_dir, names):
        return [n for n in names if n in SNAPSHOT_IGNORE]

    shutil.copytree(
        ds_root, snapshot,
        copy_function=os.link, ignore=_ignore,
        dirs_exist_ok=False, symlinks=False,
    )
    _strip_tombstoned(snapshot)
    return snapshot


def _strip_tombstoned(snapshot: Path) -> None:
    """Remove tombstoned episode data/video files in the snapshot, then rewrite
    episodes.parquet and info.json to exclude deleted rows. Breaks hardlinks
    only for those few meta files (data/video file unlink decrements refcount;
    original ds_root inodes are unaffected)."""
    eps_pq = snapshot / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    if not eps_pq.exists():
        return
    rows = pq.read_table(eps_pq).to_pylist()
    deleted = [r for r in rows if r.get("deleted")]
    if not deleted:
        return

    # 1) hardlink unlink（snapshot 側だけ消える、original は無傷）
    for row in deleted:
        ep_idx = row["episode_index"]
        chunk = ep_idx // 1000
        chunk_str = f"chunk-{chunk:03d}"
        data_path = snapshot / "data" / chunk_str / f"episode_{ep_idx:06d}.parquet"
        data_path.unlink(missing_ok=True)
        videos_dir = snapshot / "videos"
        if videos_dir.exists():
            for cam_dir in videos_dir.iterdir():
                if not cam_dir.is_dir():
                    continue
                vp = cam_dir / chunk_str / f"episode_{ep_idx:06d}.mp4"
                vp.unlink(missing_ok=True)

    # 2) episodes.parquet 再生成（dataset_from/to_index 再計算）
    kept = [r for r in rows if not r.get("deleted")]
    offset = 0
    for r in sorted(kept, key=lambda x: x["episode_index"]):
        r["dataset_from_index"] = offset
        r["dataset_to_index"] = offset + r.get("length", 0)
        offset = r["dataset_to_index"]
    if kept:
        _atomic_write_parquet(pa.Table.from_pylist(kept), eps_pq)
    else:
        # 空のときは空 schema で書き直す
        eps_pq.unlink(missing_ok=True)

    # 3) info.json totals 再計算
    info_path = snapshot / "meta" / "info.json"
    if info_path.exists():
        info = json.loads(info_path.read_text())
        info["total_episodes"] = len(kept)
        info["total_frames"] = sum(r.get("length", 0) for r in kept)
        info["splits"] = {"train": f"0:{len(kept)}"}
        _atomic_write_text(info_path, json.dumps(info, indent=2))


def collect_tombstoned_files(ds_root: Path) -> list[str]:
    """Hub-relative paths to delete via post-upload `delete_files`. Catches
    files that were uploaded in a previous push but are now tombstoned."""
    eps_pq = ds_root / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    if not eps_pq.exists():
        return []
    rows = pq.read_table(eps_pq).to_pylist()
    paths: list[str] = []
    for row in rows:
        if not row.get("deleted"):
            continue
        ep_idx = row["episode_index"]
        chunk_str = f"chunk-{ep_idx // 1000:03d}"
        paths.append(f"data/{chunk_str}/episode_{ep_idx:06d}.parquet")
        videos_dir = ds_root / "videos"
        if videos_dir.exists():
            for cam_dir in videos_dir.iterdir():
                if not cam_dir.is_dir():
                    continue
                paths.append(
                    f"videos/{cam_dir.name}/{chunk_str}/episode_{ep_idx:06d}.mp4"
                )
    return paths


def cleanup_snapshot(snapshot: Path) -> None:
    """Idempotent. Only removes dirs whose name starts with `.push-snapshot-`."""
    if snapshot.exists() and snapshot.name.startswith(".push-snapshot-"):
        shutil.rmtree(snapshot)


def cleanup_orphan_snapshots(datasets_root: Path) -> int:
    """Called at backend startup to remove orphan snapshot dirs from previous runs.
    Returns count of dirs removed."""
    if not datasets_root.exists():
        return 0
    n = 0
    for p in datasets_root.iterdir():
        if p.is_dir() and p.name.startswith(".push-snapshot-"):
            shutil.rmtree(p, ignore_errors=True)
            n += 1
    return n
```

- [ ] **Step 4: pass 確認**

```bash
bash scripts/test.sh tests/unit/test_snapshot.py -v
```

期待: 8 件 pass。

- [ ] **Step 5: コミット**

```bash
git add backend/mimicrec/cloud/snapshot.py tests/unit/test_snapshot.py
git commit -m "feat(cloud): hardlink push snapshot with tombstone stripping"
```

---

## Task 11: `cloud/hf_pusher.py` — push_dataset

**Files:**
- Create: `backend/mimicrec/cloud/hf_pusher.py`
- Test: `tests/unit/test_hf_pusher.py`

- [ ] **Step 1: failing test**

`tests/unit/test_hf_pusher.py`:

```python
from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from mimicrec.cloud.hf_pusher import push_dataset, PushResult


def _stub_snapshot(tmp_path: Path) -> Path:
    snap = tmp_path / ".push-snapshot-ds-abc"
    (snap / "data").mkdir(parents=True)
    (snap / "meta").mkdir()
    return snap


def test_push_creates_repo_then_uploads(tmp_path: Path):
    snap = _stub_snapshot(tmp_path)
    api = MagicMock()
    api.list_repo_commits.return_value = [MagicMock(commit_id="abc123")]
    with patch("mimicrec.cloud.hf_pusher.HfApi", return_value=api):
        result = push_dataset(snap, "u/d", private=True)
    assert isinstance(result, PushResult)
    assert result.commit_sha == "abc123"
    assert result.repo_id == "u/d"

    api.create_repo.assert_called_once_with(
        "u/d", repo_type="dataset", private=True, exist_ok=True,
    )
    upload_call = api.upload_large_folder.call_args
    assert upload_call.kwargs["folder_path"] == str(snap)
    assert upload_call.kwargs["repo_id"] == "u/d"
    assert upload_call.kwargs["repo_type"] == "dataset"
    assert upload_call.kwargs["private"] is True
    # ignore_patterns に必須メンバーが含まれる
    ignore = upload_call.kwargs["ignore_patterns"]
    for pat in (".pending/**", ".cache/**", ".git/**", "meta/hub.json"):
        assert pat in ignore


def test_push_calls_delete_files_when_tombstoned(tmp_path: Path):
    snap = _stub_snapshot(tmp_path)
    api = MagicMock()
    api.list_repo_commits.side_effect = [
        [MagicMock(commit_id="upload_sha")],
        [MagicMock(commit_id="delete_sha")],
    ]
    with patch("mimicrec.cloud.hf_pusher.HfApi", return_value=api):
        result = push_dataset(
            snap, "u/d", private=True,
            tombstoned_files=["data/chunk-000/episode_000000.parquet"],
        )
    api.delete_files.assert_called_once_with(
        repo_id="u/d", repo_type="dataset",
        delete_patterns=["data/chunk-000/episode_000000.parquet"],
        commit_message="cleanup tombstoned episodes",
        parent_commit="upload_sha",
    )
    # 最終 commit_sha は delete commit
    assert result.commit_sha == "delete_sha"


def test_push_skips_delete_when_no_tombstones(tmp_path: Path):
    snap = _stub_snapshot(tmp_path)
    api = MagicMock()
    api.list_repo_commits.return_value = [MagicMock(commit_id="abc123")]
    with patch("mimicrec.cloud.hf_pusher.HfApi", return_value=api):
        push_dataset(snap, "u/d", private=True)
    api.delete_files.assert_not_called()


def test_push_propagates_upload_error(tmp_path: Path):
    snap = _stub_snapshot(tmp_path)
    api = MagicMock()
    api.upload_large_folder.side_effect = RuntimeError("net down")
    with patch("mimicrec.cloud.hf_pusher.HfApi", return_value=api):
        with pytest.raises(RuntimeError):
            push_dataset(snap, "u/d", private=True)
```

- [ ] **Step 2: fail 確認**

```bash
bash scripts/test.sh tests/unit/test_hf_pusher.py -v
```

期待: ImportError。

- [ ] **Step 3: 実装**

`backend/mimicrec/cloud/hf_pusher.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import HfApi


@dataclass(frozen=True)
class PushResult:
    commit_sha: str
    repo_id: str


_IGNORE_PATTERNS = [
    ".pending/**", ".pending/",
    ".cache/**", "cache/huggingface/**",
    ".git/**", ".git",
    "meta/hub.json",
]


def push_dataset(
    src: Path,
    repo_id: str,
    *,
    private: bool,
    tombstoned_files: list[str] | None = None,
) -> PushResult:
    """Push `src` (snapshot dir) to `repo_id` on HF Hub.

    Caller is responsible for snapshot creation/cleanup and providing a clean
    tombstone-stripped src. tombstoned_files are paths to remove from a
    previous Hub revision (orphan cleanup).
    """
    api = HfApi()
    api.create_repo(repo_id, repo_type="dataset", private=private, exist_ok=True)
    api.upload_large_folder(
        folder_path=str(src),
        repo_id=repo_id,
        repo_type="dataset",
        private=private,
        ignore_patterns=list(_IGNORE_PATTERNS),
        print_report=False,
    )
    commits = api.list_repo_commits(repo_id=repo_id, repo_type="dataset")
    head_sha = commits[0].commit_id

    if tombstoned_files:
        api.delete_files(
            repo_id=repo_id, repo_type="dataset",
            delete_patterns=list(tombstoned_files),
            commit_message="cleanup tombstoned episodes",
            parent_commit=head_sha,
        )
        commits = api.list_repo_commits(repo_id=repo_id, repo_type="dataset")
        head_sha = commits[0].commit_id

    return PushResult(commit_sha=head_sha, repo_id=repo_id)
```

- [ ] **Step 4: pass 確認**

```bash
bash scripts/test.sh tests/unit/test_hf_pusher.py -v
```

期待: 4 件 pass。

- [ ] **Step 5: コミット**

```bash
git add backend/mimicrec/cloud/hf_pusher.py tests/unit/test_hf_pusher.py
git commit -m "feat(cloud): push_dataset wrapping HfApi.upload_large_folder + tombstone delete"
```

---

## Task 12: `api/util.py` — `safe_dataset_path`

**Files:**
- Create: `backend/mimicrec/api/util.py`
- Test: `tests/unit/test_safe_dataset_path.py`

- [ ] **Step 1: failing test**

`tests/unit/test_safe_dataset_path.py`:

```python
from __future__ import annotations
from pathlib import Path
import pytest

from mimicrec.api.util import safe_dataset_path, UnsafePathError


def test_safe_path_returns_concat(tmp_path: Path):
    root = tmp_path
    (root / "ds").mkdir()
    p = safe_dataset_path(root, "ds")
    assert p == root / "ds"


def test_traversal_with_dotdot_rejected(tmp_path: Path):
    root = tmp_path
    with pytest.raises(UnsafePathError):
        safe_dataset_path(root, "../etc")


def test_absolute_name_rejected(tmp_path: Path):
    with pytest.raises(UnsafePathError):
        safe_dataset_path(tmp_path, "/etc")


def test_slash_in_name_rejected(tmp_path: Path):
    with pytest.raises(UnsafePathError):
        safe_dataset_path(tmp_path, "a/b")


def test_empty_name_rejected(tmp_path: Path):
    with pytest.raises(UnsafePathError):
        safe_dataset_path(tmp_path, "")


def test_dotdot_segment_rejected_via_resolve(tmp_path: Path):
    """resolve() check も働く"""
    sub = tmp_path / "sub"
    sub.mkdir()
    with pytest.raises(UnsafePathError):
        safe_dataset_path(sub, "../sibling")
```

- [ ] **Step 2: fail 確認**

```bash
bash scripts/test.sh tests/unit/test_safe_dataset_path.py -v
```

期待: ImportError。

- [ ] **Step 3: 実装**

`backend/mimicrec/api/util.py`:

```python
from __future__ import annotations
from pathlib import Path


class UnsafePathError(ValueError):
    pass


def safe_dataset_path(root: Path, ds_name: str) -> Path:
    """Resolve `root / ds_name` and ensure it stays inside `root`.
    Rejects empty names, slashes, absolute paths, and `..` traversal.
    """
    if not ds_name or "/" in ds_name or "\\" in ds_name:
        raise UnsafePathError(f"invalid dataset name: {ds_name!r}")
    if Path(ds_name).is_absolute():
        raise UnsafePathError(f"absolute dataset name forbidden: {ds_name!r}")
    candidate = (root / ds_name).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        raise UnsafePathError(f"dataset path escapes root: {ds_name!r}")
    return candidate
```

- [ ] **Step 4: pass 確認**

```bash
bash scripts/test.sh tests/unit/test_safe_dataset_path.py -v
```

期待: 6 件 pass。

- [ ] **Step 5: コミット**

```bash
git add backend/mimicrec/api/util.py tests/unit/test_safe_dataset_path.py
git commit -m "feat(api): safe_dataset_path helper to prevent path traversal"
```

---

## Task 13: `api/routes/cloud.py` — auth-status + GET/PUT hub

**Files:**
- Create: `backend/mimicrec/api/routes/cloud.py`
- Modify: `backend/mimicrec/api/app.py`
- Test: `tests/api/test_cloud_routes.py`

このタスクでは `/api/cloud/auth-status` と `/api/datasets/{ds}/hub` (GET/PUT) のみ。POST `/hub/push` は次タスク。

- [ ] **Step 1: failing test**

`tests/api/test_cloud_routes.py`:

```python
from __future__ import annotations
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport

from mimicrec.api.app import create_app
from mimicrec.cloud.hub_meta import HubMeta, write_hub_meta, hub_meta_path
from mimicrec.cloud.push_state import PushCoordinator
from mimicrec.recording.dataset_layout import init_dataset


@pytest.fixture
def client_and_root(tmp_path):
    app = create_app()
    app.state.datasets_root = tmp_path
    app.state.push_coordinator = PushCoordinator()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), tmp_path


@pytest.mark.asyncio
async def test_auth_status_no_token(client_and_root):
    client, _ = client_and_root
    with patch("mimicrec.api.routes.cloud.HfApi") as MockApi:
        instance = MockApi.return_value
        instance.get_token.return_value = None
        async with client as ac:
            r = await ac.get("/api/cloud/auth-status")
    assert r.status_code == 200
    assert r.json()["authenticated"] is False
    assert r.json()["username"] is None


@pytest.mark.asyncio
async def test_auth_status_with_token(client_and_root):
    client, _ = client_and_root
    with patch("mimicrec.api.routes.cloud.HfApi") as MockApi:
        instance = MockApi.return_value
        instance.get_token.return_value = "hf_xxx"
        instance.whoami.return_value = {"name": "TakakiMaeda"}
        async with client as ac:
            r = await ac.get("/api/cloud/auth-status")
    assert r.status_code == 200
    assert r.json()["authenticated"] is True
    assert r.json()["username"] == "TakakiMaeda"


@pytest.mark.asyncio
async def test_get_hub_returns_null_when_unconfigured(client_and_root):
    client, root = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    async with client as ac:
        r = await ac.get("/api/datasets/ds/hub")
    assert r.status_code == 200
    body = r.json()
    assert body["config"] is None
    assert body["state"] is None
    assert body["progress"]["status"] == "idle"


@pytest.mark.asyncio
async def test_put_hub_creates_meta(client_and_root):
    client, root = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    async with client as ac:
        r = await ac.put("/api/datasets/ds/hub", json={
            "repo_id": "TakakiMaeda/learn-data-bottle",
        })
    assert r.status_code == 200
    body = r.json()
    assert body["config"]["repo_id"] == "TakakiMaeda/learn-data-bottle"
    assert body["config"]["private"] is True   # default
    assert body["config"]["auto_push"] is False
    # meta/hub.json が書かれている
    p = hub_meta_path(root / "ds")
    saved = json.loads(p.read_text())
    assert saved["repo_id"] == "TakakiMaeda/learn-data-bottle"


@pytest.mark.asyncio
async def test_put_hub_rejects_invalid_repo_id(client_and_root):
    client, root = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    async with client as ac:
        r = await ac.put("/api/datasets/ds/hub", json={"repo_id": "no-slash"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_put_hub_path_traversal_rejected(client_and_root):
    client, root = client_and_root
    async with client as ac:
        r = await ac.put("/api/datasets/..%2Fetc/hub", json={"repo_id": "u/d"})
    # ..%2F は dataset name として不正 → 400 / 404 のいずれか
    assert r.status_code in (400, 404)
```

- [ ] **Step 2: fail 確認**

```bash
bash scripts/test.sh tests/api/test_cloud_routes.py -v
```

期待: ルート未登録 / 404 で fail。

- [ ] **Step 3: cloud.py 実装**

`backend/mimicrec/api/routes/cloud.py`:

```python
from __future__ import annotations
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from huggingface_hub import HfApi
from pydantic import BaseModel, Field

from mimicrec.api.deps import get_datasets_root
from mimicrec.api.util import safe_dataset_path, UnsafePathError
from mimicrec.cloud.hub_meta import HubMeta, read_hub_meta, write_hub_meta
from mimicrec.cloud.push_state import PushProgress

router = APIRouter()

_REPO_ID_RE = re.compile(r"^[\w][\w.-]*\/[\w][\w.-]*$")
_AUTH_TTL_SEC = 60.0


class HubConfig(BaseModel):
    repo_id: str = Field(..., min_length=3)
    private: bool = True
    auto_push: bool = False


class AuthStatus(BaseModel):
    authenticated: bool
    username: str | None
    checked_at: str


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_ds(request: Request, ds: str) -> Path:
    root = get_datasets_root(request.app)
    try:
        ds_root = safe_dataset_path(root, ds)
    except UnsafePathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ds_root.exists():
        raise HTTPException(status_code=404, detail=f"dataset '{ds}' not found")
    return ds_root


@router.get("/cloud/auth-status")
async def auth_status(request: Request, refresh: int = 0) -> AuthStatus:
    cache = getattr(request.app.state, "auth_cache", None)
    now = time.monotonic()
    if not refresh and cache is not None and now - cache["t"] < _AUTH_TTL_SEC:
        return AuthStatus(**cache["value"])

    api = HfApi()
    token = api.get_token()
    username: str | None = None
    if token:
        try:
            who = api.whoami()
            username = who.get("name") if isinstance(who, dict) else getattr(who, "name", None)
        except Exception:
            username = None
    value = {
        "authenticated": bool(token),
        "username": username,
        "checked_at": _iso_now(),
    }
    request.app.state.auth_cache = {"t": now, "value": value}
    return AuthStatus(**value)


@router.get("/datasets/{ds}/hub")
async def get_hub(request: Request, ds: str):
    ds_root = _resolve_ds(request, ds)
    meta = read_hub_meta(ds_root)
    coord = request.app.state.push_coordinator
    progress = coord.progress.get(ds, PushProgress())
    return {
        "config": (
            None if meta is None else
            {"repo_id": meta.repo_id, "private": meta.private, "auto_push": meta.auto_push}
        ),
        "state": (
            None if meta is None else
            {
                "last_pushed_at": meta.last_pushed_at,
                "last_pushed_commit_sha": meta.last_pushed_commit_sha,
                "last_pushed_manifest_hash": meta.last_pushed_manifest_hash,
                "last_push_error": meta.last_push_error,
            }
        ),
        "progress": {
            "status": progress.status,
            "started_at": progress.started_at,
            "ended_at": progress.ended_at,
            "error": progress.error,
        },
    }


@router.put("/datasets/{ds}/hub")
async def put_hub(request: Request, ds: str, body: HubConfig):
    ds_root = _resolve_ds(request, ds)
    if not _REPO_ID_RE.match(body.repo_id):
        raise HTTPException(status_code=400, detail=f"invalid repo_id: {body.repo_id!r}")
    existing = read_hub_meta(ds_root)
    new = HubMeta(
        repo_id=body.repo_id,
        private=body.private,
        auto_push=body.auto_push,
        last_pushed_at=existing.last_pushed_at if existing else None,
        last_pushed_commit_sha=existing.last_pushed_commit_sha if existing else None,
        last_pushed_manifest_hash=existing.last_pushed_manifest_hash if existing else None,
        last_push_error=existing.last_push_error if existing else None,
    )
    write_hub_meta(ds_root, new)
    return await get_hub(request, ds)
```

- [ ] **Step 4: app.py にルーター登録 + coordinator 初期化**

`backend/mimicrec/api/app.py`:

冒頭 import 追加:
```python
from mimicrec.api.routes import configs, datasets, episode, inference, replay, session, settings, cloud
from mimicrec.cloud.push_state import PushCoordinator
```

`create_app()` 内、ルーター登録近辺:
```python
    app.state.push_coordinator = PushCoordinator()
    app.state.auth_cache = None
    ...
    app.include_router(cloud.router, prefix="/api")
```

- [ ] **Step 5: pass 確認**

```bash
bash scripts/test.sh tests/api/test_cloud_routes.py -v
```

期待: 6 件 pass。

- [ ] **Step 6: コミット**

```bash
git add backend/mimicrec/api/routes/cloud.py backend/mimicrec/api/app.py tests/api/test_cloud_routes.py
git commit -m "feat(api): /cloud/auth-status and /datasets/{ds}/hub GET/PUT"
```

---

## Task 14: `POST /api/datasets/{ds}/hub/push` — 同期前段 + バックグラウンド task

**Files:**
- Modify: `backend/mimicrec/api/routes/cloud.py`
- Test: 拡張 `tests/api/test_cloud_routes.py`

ここで **status code 順**: path → 存在 → auth → 設定 → 重複。

- [ ] **Step 1: failing test を追加**

`tests/api/test_cloud_routes.py` に追記:

```python
@pytest.mark.asyncio
async def test_post_push_401_when_no_token(client_and_root):
    client, root = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    write_hub_meta(root / "ds", HubMeta(repo_id="u/d"))
    with patch("mimicrec.api.routes.cloud.HfApi") as MockApi:
        MockApi.return_value.get_token.return_value = None
        async with client as ac:
            r = await ac.post("/api/datasets/ds/hub/push")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_post_push_400_when_hub_unconfigured(client_and_root):
    client, root = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    with patch("mimicrec.api.routes.cloud.HfApi") as MockApi:
        MockApi.return_value.get_token.return_value = "hf_xxx"
        async with client as ac:
            r = await ac.post("/api/datasets/ds/hub/push")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_post_push_404_when_dataset_absent(client_and_root):
    client, _ = client_and_root
    with patch("mimicrec.api.routes.cloud.HfApi") as MockApi:
        MockApi.return_value.get_token.return_value = "hf_xxx"
        async with client as ac:
            r = await ac.post("/api/datasets/nope/hub/push")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_post_push_202_then_409_for_duplicate(client_and_root, monkeypatch):
    client, root = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    write_hub_meta(root / "ds", HubMeta(repo_id="u/d"))

    # _push_task をハングさせて in-flight 中の二重 POST を検証
    import asyncio as _a
    started = _a.Event()
    release = _a.Event()

    async def hanging_task(*a, **kw):
        started.set()
        await release.wait()

    monkeypatch.setattr("mimicrec.api.routes.cloud._run_push_with_release", hanging_task)

    with patch("mimicrec.api.routes.cloud.HfApi") as MockApi:
        MockApi.return_value.get_token.return_value = "hf_xxx"
        async with client as ac:
            r1 = await ac.post("/api/datasets/ds/hub/push")
            assert r1.status_code == 202
            await started.wait()
            r2 = await ac.post("/api/datasets/ds/hub/push")
            assert r2.status_code == 409
            release.set()
```

- [ ] **Step 2: fail 確認**

```bash
bash scripts/test.sh tests/api/test_cloud_routes.py -v
```

期待: 新規 4 件 fail（ルート未実装）。

- [ ] **Step 3: `cloud.py` に push エンドポイント + バックグラウンド実装**

`backend/mimicrec/api/routes/cloud.py` に追加:

```python
import asyncio
from mimicrec.cloud.hf_pusher import push_dataset
from mimicrec.cloud.hub_meta import compute_manifest_hash
from mimicrec.cloud.snapshot import (
    make_push_snapshot, cleanup_snapshot, collect_tombstoned_files,
)


@router.post("/datasets/{ds}/hub/push", status_code=202)
async def post_push(request: Request, ds: str):
    ds_root = _resolve_ds(request, ds)   # path 400 / 存在 404
    api = HfApi()
    if not api.get_token():
        raise HTTPException(status_code=401, detail="not authenticated; run `huggingface-cli login`")
    meta = read_hub_meta(ds_root)
    if meta is None:
        raise HTTPException(status_code=400, detail="hub not configured for this dataset")
    coord = request.app.state.push_coordinator
    if not coord.try_reserve(ds):
        raise HTTPException(status_code=409, detail="push already in flight")
    coord.progress[ds] = PushProgress(
        status="queued", repo_id=meta.repo_id, started_at=_iso_now()
    )
    asyncio.create_task(_run_push_with_release(request.app, ds, ds_root))
    return {"status": "queued"}


async def _run_push_with_release(app, ds_name: str, ds_root: Path):
    coord = app.state.push_coordinator
    try:
        await _push_task(app, ds_name, ds_root)
    finally:
        coord.release(ds_name)


async def _push_task(app, ds_name: str, ds_root: Path):
    coord = app.state.push_coordinator
    save_lock = coord.get_save_lock(ds_name)
    coord.progress[ds_name].status = "uploading"

    snap: Path | None = None
    meta_at_start = None
    tombstoned: list[str] = []
    start_hash: str | None = None
    push_error: BaseException | None = None
    result = None

    def _take_snapshot():
        with save_lock:
            m = read_hub_meta(ds_root)
            if m is None:
                raise RuntimeError("hub config disappeared during push")
            t = collect_tombstoned_files(ds_root)
            sh = compute_manifest_hash(ds_root)
            s = make_push_snapshot(ds_root)
            return m, t, sh, s

    try:
        meta_at_start, tombstoned, start_hash, snap = await asyncio.to_thread(_take_snapshot)
    except Exception as e:
        await asyncio.to_thread(_finalize_with_error, app, ds_name, ds_root, e)
        return

    inner = asyncio.create_task(asyncio.to_thread(
        push_dataset, snap, meta_at_start.repo_id,
        private=meta_at_start.private, tombstoned_files=tombstoned,
    ))
    try:
        result = await asyncio.shield(inner)
    except asyncio.CancelledError:
        # thread はキャンセルできないので必ず完了を待つ
        try:
            result = await inner
        except BaseException as e:
            push_error = e
    except Exception as e:
        push_error = e

    def _finalize():
        try:
            with save_lock:
                current = read_hub_meta(ds_root) or meta_at_start
                end_hash = compute_manifest_hash(ds_root)
                if push_error or result is None:
                    msg = str(push_error) if push_error else "push aborted"
                    current.last_push_error = msg
                    coord.progress[ds_name].status = "error"
                    coord.progress[ds_name].error = msg
                else:
                    current.last_pushed_commit_sha = result.commit_sha
                    current.last_pushed_at = _iso_now()
                    current.last_pushed_manifest_hash = (
                        start_hash if end_hash == start_hash else None
                    )
                    current.last_push_error = None
                    coord.progress[ds_name].status = "done"
                    coord.progress[ds_name].last_pushed_commit_sha = result.commit_sha
                coord.progress[ds_name].ended_at = _iso_now()
                write_hub_meta(ds_root, current)
        finally:
            if snap is not None:
                cleanup_snapshot(snap)

    await asyncio.to_thread(_finalize)


def _finalize_with_error(app, ds_name: str, ds_root: Path, error: BaseException):
    coord = app.state.push_coordinator
    save_lock = coord.get_save_lock(ds_name)
    with save_lock:
        existing = read_hub_meta(ds_root)
        if existing is not None:
            existing.last_push_error = str(error)
            write_hub_meta(ds_root, existing)
        coord.progress[ds_name].status = "error"
        coord.progress[ds_name].error = str(error)
        coord.progress[ds_name].ended_at = _iso_now()
```

- [ ] **Step 4: pass 確認**

```bash
bash scripts/test.sh tests/api/test_cloud_routes.py -v
```

期待: 全件 pass（既存 6 + 新規 4 = 10）。

- [ ] **Step 5: コミット**

```bash
git add backend/mimicrec/api/routes/cloud.py tests/api/test_cloud_routes.py
git commit -m "feat(api): POST /datasets/{ds}/hub/push with snapshot + background upload"
```

---

## Task 15: `DELETE /datasets/{ds}` を coordinator 連携

**Files:**
- Modify: `backend/mimicrec/api/routes/datasets.py:56-63`

- [ ] **Step 1: failing test を `tests/api/test_cloud_routes.py` に追加**

```python
@pytest.mark.asyncio
async def test_delete_dataset_409_when_push_in_flight(client_and_root, monkeypatch):
    client, root = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    coord = client._transport.app.state.push_coordinator
    coord.try_reserve("ds")
    try:
        async with client as ac:
            r = await ac.delete("/api/datasets/ds")
        assert r.status_code == 409
    finally:
        coord.release("ds")


@pytest.mark.asyncio
async def test_delete_dataset_drops_coordinator_state(client_and_root):
    client, root = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    coord = client._transport.app.state.push_coordinator
    coord.get_save_lock("ds")   # state を作る
    coord.progress["ds"] = PushProgress(status="done")
    async with client as ac:
        r = await ac.delete("/api/datasets/ds")
    assert r.status_code == 204
    assert "ds" not in coord.save_locks
    assert "ds" not in coord.progress
```

- [ ] **Step 2: fail 確認**

```bash
bash scripts/test.sh tests/api/test_cloud_routes.py::test_delete_dataset_409_when_push_in_flight tests/api/test_cloud_routes.py::test_delete_dataset_drops_coordinator_state -v
```

期待: 既存 DELETE が in_flight を見ないので fail（200/204 で通る or coordinator state 残存）。

- [ ] **Step 3: datasets.py の DELETE を変更**

`backend/mimicrec/api/routes/datasets.py:56-63`:

変更前:
```python
@router.delete("/datasets/{ds}", status_code=204)
async def delete_dataset(request: Request, ds: str):
    import shutil
    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")
    shutil.rmtree(ds_root)
```

変更後:
```python
@router.delete("/datasets/{ds}", status_code=204)
async def delete_dataset(request: Request, ds: str):
    import shutil
    from mimicrec.api.util import safe_dataset_path, UnsafePathError
    root = get_datasets_root(request.app)
    try:
        ds_root = safe_dataset_path(root, ds)
    except UnsafePathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ds_root.exists():
        raise HTTPException(status_code=404, detail=f"dataset '{ds}' not found")
    coord = request.app.state.push_coordinator
    if ds in coord.in_flight:
        raise HTTPException(status_code=409, detail="cannot delete: push in flight")
    save_lock = coord.get_save_lock(ds)
    with save_lock:
        shutil.rmtree(ds_root)
        coord.drop_dataset(ds)
```

- [ ] **Step 4: pass 確認**

```bash
bash scripts/test.sh tests/api/test_cloud_routes.py tests/api/test_dataset_routes.py -v
```

期待: 全件 pass。

- [ ] **Step 5: コミット**

```bash
git add backend/mimicrec/api/routes/datasets.py tests/api/test_cloud_routes.py
git commit -m "feat(api): DELETE /datasets/{ds} coordinates with push in-flight"
```

---

## Task 16: API ルートの annotate / tasks / tombstone に coordinator + ds_name を渡す

**Files:**
- Modify: `backend/mimicrec/api/routes/datasets.py`

- [ ] **Step 1: failing test**

`tests/api/test_route_lock_participation.py`:

```python
from __future__ import annotations
import pytest
from httpx import AsyncClient, ASGITransport

from mimicrec.api.app import create_app
from mimicrec.cloud.push_state import PushCoordinator
from mimicrec.recording.dataset_layout import init_dataset


@pytest.fixture
def client_and_root(tmp_path):
    app = create_app()
    app.state.datasets_root = tmp_path
    app.state.push_coordinator = PushCoordinator()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), tmp_path


@pytest.mark.asyncio
async def test_post_tasks_acquires_lock(client_and_root, monkeypatch):
    client, root = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])

    captured = {}
    from mimicrec.recording import metadata as meta_mod
    real = meta_mod.upsert_task

    def spy(meta_dir, name, instr, *, coordinator=None, ds_name=None):
        captured["coordinator"] = coordinator
        captured["ds_name"] = ds_name
        return real(meta_dir, name, instr, coordinator=coordinator, ds_name=ds_name)

    monkeypatch.setattr(meta_mod, "upsert_task", spy)
    async with client as ac:
        r = await ac.post("/api/datasets/ds/tasks", json={
            "name": "pick", "instruction": "pick the ball",
        })
    assert r.status_code == 200
    assert captured["coordinator"] is not None
    assert captured["ds_name"] == "ds"


@pytest.mark.asyncio
async def test_delete_episode_acquires_lock(client_and_root, monkeypatch):
    client, root = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    # tombstone 用の episode を 1 件 仕込む
    from mimicrec.recording.metadata import append_episode
    append_episode(
        root / "ds" / "meta",
        {"episode_index": 0, "task": "t", "num_frames": 1, "duration_sec": 0.1, "cameras": []},
    )

    from mimicrec.recording import metadata as meta_mod
    captured = {}
    real = meta_mod.tombstone_episode

    def spy(meta_dir, idx, deleted_at_unix, *, coordinator=None, ds_name=None):
        captured["coordinator"] = coordinator
        captured["ds_name"] = ds_name
        return real(meta_dir, idx, deleted_at_unix, coordinator=coordinator, ds_name=ds_name)

    monkeypatch.setattr(meta_mod, "tombstone_episode", spy)
    async with client as ac:
        r = await ac.delete("/api/datasets/ds/episodes/0")
    assert r.status_code == 204
    assert captured["coordinator"] is not None
    assert captured["ds_name"] == "ds"
```

- [ ] **Step 2: fail 確認**

```bash
bash scripts/test.sh tests/api/test_route_lock_participation.py -v
```

期待: coordinator/ds_name が None で fail。

- [ ] **Step 3: datasets.py のルートを変更**

`backend/mimicrec/api/routes/datasets.py` の以下を修正:

`delete_episode` (line 151 付近):
```python
@router.delete("/datasets/{ds}/episodes/{idx}", status_code=204)
async def delete_episode(request: Request, ds: str, idx: int):
    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")
    coord = request.app.state.push_coordinator
    tombstone_episode(
        ds_root / "meta", idx, deleted_at_unix=int(time.time()),
        coordinator=coord, ds_name=ds,
    )
```

`create_task` (line 178 付近):
```python
@router.post("/datasets/{ds}/tasks")
async def create_task(request: Request, ds: str, body: CreateTaskRequest):
    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")
    coord = request.app.state.push_coordinator
    upsert_task(
        ds_root / "meta", body.name, body.instruction,
        coordinator=coord, ds_name=ds,
    )
    ...
```

`annotate_episode_subtasks` (line 309 付近) と `annotate_all_episodes` (line 357 付近) で `save_annotations` 呼び出しに coordinator/ds_name を追加:

```python
save_annotations(ds_root, idx, segments,
                 coordinator=request.app.state.push_coordinator, ds_name=ds)
```

annotate_all_episodes 内の thread で動く `run()` の中の `save_annotations(...)` も同様。

- [ ] **Step 4: pass 確認**

```bash
bash scripts/test.sh tests/api/test_route_lock_participation.py tests/api/test_dataset_routes.py tests/api/test_episode_routes.py -v
```

期待: 全件 pass。

- [ ] **Step 5: コミット**

```bash
git add backend/mimicrec/api/routes/datasets.py tests/api/test_route_lock_participation.py
git commit -m "refactor(api): pass coordinator/ds_name to writer functions in dataset routes"
```

---

## Task 17: `PendingEpisode` に coordinator/ds_name を注入 + auto-push トリガ

**Files:**
- Modify: `backend/mimicrec/recording/pending.py`
- Modify: `backend/mimicrec/api/deps.py` (SessionManager 構築時)
- Modify: `backend/mimicrec/session/lifecycle.py` (SessionManager が coordinator + app_loop を保持)

- [ ] **Step 1: failing test**

`tests/integration/test_auto_push_flow.py`:

```python
from __future__ import annotations
import asyncio
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicrec.cloud.hub_meta import HubMeta, write_hub_meta
from mimicrec.cloud.push_state import PushCoordinator
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.pending import PendingEpisode


@pytest.mark.asyncio
async def test_auto_push_skips_when_disabled(tmp_path: Path):
    init_dataset(tmp_path / "ds", fps=30, joint_names=["j0"], camera_names=[])
    coord = PushCoordinator()
    write_hub_meta(tmp_path / "ds", HubMeta(repo_id="u/d", auto_push=False))

    triggered = []

    def fake_trigger(ds_root, ds_name, app_loop):
        triggered.append(ds_name)

    loop = asyncio.get_running_loop()
    ep = PendingEpisode.open(
        tmp_path / "ds", episode_index=0,
        coordinator=coord, ds_name="ds", app_loop=loop,
    )
    ep.append_row({"action": [0.1], "observation.state": [0.0],
                   "timestamp": 0.0, "frame_index": 0,
                   "episode_index": 0, "index": 0, "task_index": 0})
    ep.finalize()
    ep.save({"episode_index": 0, "task": "t", "num_frames": 1,
             "duration_sec": 0.0, "cameras": [], "fps": 30},
            _auto_push_trigger=fake_trigger)
    assert triggered == []


@pytest.mark.asyncio
async def test_auto_push_fires_when_enabled(tmp_path: Path):
    init_dataset(tmp_path / "ds", fps=30, joint_names=["j0"], camera_names=[])
    coord = PushCoordinator()
    write_hub_meta(tmp_path / "ds", HubMeta(repo_id="u/d", auto_push=True))

    triggered = []

    def fake_trigger(ds_root, ds_name, app_loop):
        triggered.append(ds_name)

    loop = asyncio.get_running_loop()
    ep = PendingEpisode.open(
        tmp_path / "ds", episode_index=0,
        coordinator=coord, ds_name="ds", app_loop=loop,
    )
    ep.append_row({"action": [0.1], "observation.state": [0.0],
                   "timestamp": 0.0, "frame_index": 0,
                   "episode_index": 0, "index": 0, "task_index": 0})
    ep.finalize()
    ep.save({"episode_index": 0, "task": "t", "num_frames": 1,
             "duration_sec": 0.0, "cameras": [], "fps": 30},
            _auto_push_trigger=fake_trigger)
    assert triggered == ["ds"]
```

- [ ] **Step 2: fail 確認**

```bash
bash scripts/test.sh tests/integration/test_auto_push_flow.py -v
```

期待: TypeError（kwargs 未対応） で fail。

- [ ] **Step 3: pending.py を改修**

`backend/mimicrec/recording/pending.py`:

```python
class PendingEpisode:
    def __init__(self, paths, episode_index, *,
                 coordinator=None, ds_name=None, app_loop=None):
        self._paths = paths
        self._episode_index = episode_index
        self._stage = paths.pending_dir / f"ep_{episode_index:06d}"
        self._rows = []
        self._finalized = False
        self._coordinator = coordinator
        self._ds_name = ds_name
        self._app_loop = app_loop

    @classmethod
    def open(cls, ds_root, episode_index, *,
             coordinator=None, ds_name=None, app_loop=None):
        p = dataset_paths(ds_root)
        p.pending_dir.mkdir(parents=True, exist_ok=True)
        inst = cls(p, episode_index,
                   coordinator=coordinator, ds_name=ds_name, app_loop=app_loop)
        if inst._stage.exists():
            shutil.rmtree(inst._stage)
        inst._stage.mkdir(parents=True)
        return inst

    def save(self, metadata_extra: dict, *, _auto_push_trigger=None) -> None:
        if not self._finalized:
            raise RuntimeError("call finalize() before save()")

        coord = self._coordinator
        ds_name = self._ds_name

        def _do_save():
            # 既存 save 本体を関数化（rename + atomic write parquet + append_episode）
            # 既存ロジックそのまま、ただし append_episode に coordinator/ds_name を渡す
            ...
            from mimicrec.recording.atomic_io import _atomic_write_parquet
            _atomic_write_parquet(table, dst)
            src.unlink()
            for mp4 in self._stage.glob("*.mp4"):
                cam_name = mp4.stem
                vdst = self._paths.episode_video(chunk_idx, cam_name, self._episode_index)
                vdst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(mp4), str(vdst))
            from mimicrec.recording.metadata import append_episode
            append_episode(
                self._paths.meta_dir, metadata_extra,
                coordinator=coord, ds_name=ds_name,
            )
            shutil.rmtree(self._stage)

        if coord is not None and ds_name is not None:
            with coord.get_save_lock(ds_name):
                _do_save()
        else:
            _do_save()

        # auto-push トリガ（lock 解放後）
        if coord is not None and ds_name is not None and self._app_loop is not None:
            ds_root = self._paths.root
            trigger = _auto_push_trigger or _maybe_trigger_auto_push
            trigger(ds_root, ds_name, self._app_loop)


def _maybe_trigger_auto_push(ds_root, ds_name, app_loop):
    """save() 完了後に呼ばれる。hub.json 読み込み→ auto_push==true なら enqueue。"""
    from mimicrec.cloud.hub_meta import read_hub_meta
    meta = read_hub_meta(ds_root)
    if meta is None or not meta.auto_push:
        return
    # event loop 上で push を起動（実装は次タスクで）
    # ここでは存在の確認まで（実 enqueue は Task 18 で）
    return  # placeholder; full enqueue wired in Task 18
```

`PendingEpisode.save()` の既存実装を参考に `_do_save()` の中身を埋める（src/dst の書き換えロジックは既存通り）。

- [ ] **Step 4: deps.py / lifecycle.py で coordinator + app_loop を渡す**

`backend/mimicrec/api/deps.py` の `create_session_from_request()` 末尾:

```python
    # coordinator + event loop を SessionManager に注入
    coord = app.state.push_coordinator
    sm = SessionManager(
        dataset_root=ds_root,
        ...
        coordinator=coord,
        ds_name=req.dataset,
    )
    return sm
```

`backend/mimicrec/session/lifecycle.py` の `SessionManager.__init__`:

```python
    def __init__(self, ..., coordinator=None, ds_name=None):
        ...
        self._coordinator = coordinator
        self._ds_name = ds_name
        try:
            self._app_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._app_loop = None
```

`PendingEpisode.open()` を呼ぶ箇所で coordinator/ds_name/app_loop を渡す。

- [ ] **Step 5: pass 確認**

```bash
bash scripts/test.sh tests/integration/test_auto_push_flow.py tests/unit/test_pending_episode.py tests/unit/test_pending_atomic.py -v
```

期待: 全件 pass。

- [ ] **Step 6: コミット**

```bash
git add backend/mimicrec/recording/pending.py backend/mimicrec/api/deps.py backend/mimicrec/session/lifecycle.py tests/integration/test_auto_push_flow.py
git commit -m "feat(recording): inject coordinator/ds_name/app_loop into PendingEpisode + auto-push hook"
```

---

## Task 18: auto-push の実 enqueue 配線

**Files:**
- Modify: `backend/mimicrec/recording/pending.py` (`_maybe_trigger_auto_push` 完成)
- Modify: `backend/mimicrec/api/routes/cloud.py` (再エクスポート)

- [ ] **Step 1: failing test を `tests/integration/test_auto_push_flow.py` に追加**

```python
@pytest.mark.asyncio
async def test_auto_push_calls_run_push_with_release(tmp_path, monkeypatch):
    init_dataset(tmp_path / "ds", fps=30, joint_names=["j0"], camera_names=[])
    coord = PushCoordinator()
    write_hub_meta(tmp_path / "ds", HubMeta(repo_id="u/d", auto_push=True))

    enqueued = []

    async def fake_run(app, ds_name, ds_root):
        enqueued.append(ds_name)

    # _run_push_with_release を fake に
    from mimicrec.api.routes import cloud as cloud_mod
    monkeypatch.setattr(cloud_mod, "_run_push_with_release", fake_run)

    class FakeApp:
        state = type("S", (), {"push_coordinator": coord, "datasets_root": tmp_path})()

    loop = asyncio.get_running_loop()
    # PendingEpisode 経由で auto-push を発火
    ep = PendingEpisode.open(
        tmp_path / "ds", episode_index=0,
        coordinator=coord, ds_name="ds", app_loop=loop,
    )
    # app への参照を pending に渡す（実装次第。lifecycle 経由で渡しても可）
    ep._app = FakeApp()   # 暫定: 実装に合わせる
    ep.append_row({"action": [0.1], "observation.state": [0.0],
                   "timestamp": 0.0, "frame_index": 0,
                   "episode_index": 0, "index": 0, "task_index": 0})
    ep.finalize()
    ep.save({"episode_index": 0, "task": "t", "num_frames": 1,
             "duration_sec": 0.0, "cameras": [], "fps": 30})

    # event loop に schedule された task が走るのを待つ
    await asyncio.sleep(0.1)
    assert enqueued == ["ds"]
```

- [ ] **Step 2: fail 確認**

```bash
bash scripts/test.sh tests/integration/test_auto_push_flow.py::test_auto_push_calls_run_push_with_release -v
```

- [ ] **Step 3: pending.py の `_maybe_trigger_auto_push` を完成**

`backend/mimicrec/recording/pending.py`:

```python
def _maybe_trigger_auto_push(ds_root, ds_name, app_loop, app=None):
    """save() 完了後に呼ばれる。hub.json read → auto_push==true なら enqueue。"""
    from mimicrec.cloud.hub_meta import read_hub_meta
    meta = read_hub_meta(ds_root)
    if meta is None or not meta.auto_push:
        return
    if app is None:
        return  # SessionManager が app を渡していない（テスト等）
    coord = app.state.push_coordinator
    if not coord.try_reserve(ds_name):
        return
    from mimicrec.cloud.push_state import PushProgress
    coord.progress[ds_name] = PushProgress(
        status="queued", repo_id=meta.repo_id, started_at=_iso_now()
    )
    from mimicrec.api.routes.cloud import _run_push_with_release
    try:
        app_loop.call_soon_threadsafe(
            lambda: asyncio.create_task(_run_push_with_release(app, ds_name, ds_root))
        )
    except RuntimeError:
        coord.release(ds_name)
        coord.progress[ds_name].status = "error"
        coord.progress[ds_name].error = "event loop unavailable"


def _iso_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
```

`PendingEpisode` に `_app` 属性を追加（SessionManager から渡す）:

```python
class PendingEpisode:
    def __init__(self, paths, episode_index, *,
                 coordinator=None, ds_name=None, app_loop=None, app=None):
        ...
        self._app = app
```

`save()` の最後の auto-push 呼び出し:
```python
        if coord is not None and ds_name is not None and self._app_loop is not None:
            ds_root = self._paths.root
            (_auto_push_trigger or _maybe_trigger_auto_push)(
                ds_root, ds_name, self._app_loop, app=self._app,
            )
```

- [ ] **Step 4: SessionManager 経由で `app` を渡す**

`backend/mimicrec/session/lifecycle.py`:

```python
    def __init__(self, ..., coordinator=None, ds_name=None, app=None):
        ...
        self._app = app
```

`PendingEpisode.open(...)` 呼び出しで `app=self._app` を渡す。

`backend/mimicrec/api/deps.py`:

```python
    sm = SessionManager(
        ...
        coordinator=app.state.push_coordinator,
        ds_name=req.dataset,
        app=app,
    )
```

- [ ] **Step 5: pass 確認**

```bash
bash scripts/test.sh tests/integration/test_auto_push_flow.py -v
```

期待: 全件 pass。

- [ ] **Step 6: コミット**

```bash
git add backend/mimicrec/recording/pending.py backend/mimicrec/session/lifecycle.py backend/mimicrec/api/deps.py tests/integration/test_auto_push_flow.py
git commit -m "feat(recording): wire auto-push enqueue via call_soon_threadsafe"
```

---

## Task 19: 起動時の orphan snapshot cleanup

**Files:**
- Modify: `backend/mimicrec/api/app.py`

- [ ] **Step 1: failing test**

`tests/api/test_startup_cleanup.py`:

```python
from __future__ import annotations
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from mimicrec.api.app import create_app


@pytest.mark.asyncio
async def test_orphan_snapshots_removed_on_startup(tmp_path: Path):
    orphan = tmp_path / ".push-snapshot-stale-deadbeef"
    orphan.mkdir()
    (orphan / "junk").write_text("x")
    legit = tmp_path / "legit_dataset"
    legit.mkdir()

    app = create_app()
    app.state.datasets_root = tmp_path

    # startup イベントを実行
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.get("/api/cloud/auth-status")  # 起動を発火

    assert not orphan.exists()
    assert legit.exists()
```

- [ ] **Step 2: fail 確認**

```bash
bash scripts/test.sh tests/api/test_startup_cleanup.py -v
```

- [ ] **Step 3: app.py に startup hook**

`backend/mimicrec/api/app.py`:

```python
from contextlib import asynccontextmanager
from mimicrec.cloud.snapshot import cleanup_orphan_snapshots


@asynccontextmanager
async def _lifespan(app):
    root = getattr(app.state, "datasets_root", None)
    if root is not None:
        cleanup_orphan_snapshots(Path(root))
    yield


def create_app():
    app = FastAPI(lifespan=_lifespan)
    ...
```

既に lifespan があれば追加し、無ければ新規。

- [ ] **Step 4: pass 確認**

```bash
bash scripts/test.sh tests/api/test_startup_cleanup.py -v
```

- [ ] **Step 5: コミット**

```bash
git add backend/mimicrec/api/app.py tests/api/test_startup_cleanup.py
git commit -m "feat(api): cleanup orphan .push-snapshot-* dirs on startup"
```

---

## Task 20: Frontend `api/cloud.ts`

**Files:**
- Create: `frontend/src/api/cloud.ts`

このタスクには frontend test は無し（現状の MimicRec frontend に test 基盤が確立されていないため）。型と関数だけ。

- [ ] **Step 1: ファイル作成**

`frontend/src/api/cloud.ts`:

```typescript
import { apiFetch } from "./client";

export interface AuthStatus {
  authenticated: boolean;
  username: string | null;
  checked_at: string;
}

export interface HubConfig {
  repo_id: string;
  private: boolean;
  auto_push: boolean;
}

export interface HubState {
  last_pushed_at: string | null;
  last_pushed_commit_sha: string | null;
  last_pushed_manifest_hash: string | null;
  last_push_error: string | null;
}

export interface HubProgress {
  status: "idle" | "queued" | "uploading" | "done" | "error";
  started_at: string | null;
  ended_at: string | null;
  error: string | null;
}

export interface HubResponse {
  config: HubConfig | null;
  state: HubState | null;
  progress: HubProgress;
}

export const fetchAuthStatus = (refresh = false) =>
  apiFetch<AuthStatus>(`/api/cloud/auth-status${refresh ? "?refresh=1" : ""}`);

export const fetchHub = (ds: string) =>
  apiFetch<HubResponse>(`/api/datasets/${encodeURIComponent(ds)}/hub`);

export const putHub = (ds: string, body: HubConfig) =>
  apiFetch<HubResponse>(`/api/datasets/${encodeURIComponent(ds)}/hub`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const postHubPush = (ds: string) =>
  apiFetch<{ status: string }>(`/api/datasets/${encodeURIComponent(ds)}/hub/push`, {
    method: "POST",
  });
```

- [ ] **Step 2: TypeScript 型チェックが通ることを確認**

```bash
cd frontend && pnpm exec tsc --noEmit
```

期待: `frontend/src/api/cloud.ts` 関連のエラーなし。

- [ ] **Step 3: コミット**

```bash
git add frontend/src/api/cloud.ts
git commit -m "feat(frontend): cloud API client (auth-status + hub config + push)"
```

---

## Task 21: Frontend Hub セクション UI

**Files:**
- Modify: `frontend/src/pages/DatasetsPage.tsx`

- [ ] **Step 1: Hub セクションを既存 dataset 行の中に追加**

`frontend/src/pages/DatasetsPage.tsx` の「dataset 一覧の各行」内に `<HubSection ds={dsName} />` を組み込み、コンポーネント定義をファイル末尾に追加:

```tsx
import { useEffect, useState } from "react";
import { fetchAuthStatus, fetchHub, putHub, postHubPush, HubResponse, AuthStatus, HubConfig } from "../api/cloud";

function HubSection({ ds }: { ds: string }) {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [hub, setHub] = useState<HubResponse | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<HubConfig>({ repo_id: "", private: true, auto_push: false });
  const [saving, setSaving] = useState(false);
  const [pushing, setPushing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 初回ロード + 認証
  useEffect(() => {
    fetchAuthStatus().then(setAuth).catch(() => setAuth(null));
    fetchHub(ds).then((r) => {
      setHub(r);
      if (r.config) setDraft(r.config);
    }).catch(() => setHub(null));
  }, [ds]);

  // uploading 中だけ 2 秒間隔ポーリング
  useEffect(() => {
    if (hub?.progress.status !== "uploading" && hub?.progress.status !== "queued") return;
    const t = setInterval(async () => {
      try {
        const r = await fetchHub(ds);
        setHub(r);
        if (r.progress.status === "done" || r.progress.status === "error") {
          clearInterval(t);
        }
      } catch (e) {
        setError(String(e));
      }
    }, 2000);
    return () => clearInterval(t);
  }, [ds, hub?.progress.status]);

  const onSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const r = await putHub(ds, draft);
      setHub(r);
      setEditing(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const onPush = async () => {
    setPushing(true);
    setError(null);
    try {
      await postHubPush(ds);
      const r = await fetchHub(ds);
      setHub(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setPushing(false);
    }
  };

  return (
    <div className="border-t border-gray-200 mt-3 pt-3 text-sm">
      <div className="flex items-center gap-2 mb-2">
        <strong>HF Hub:</strong>
        {auth?.authenticated ? (
          <span className="text-green-700">@{auth.username ?? "(unknown)"}</span>
        ) : (
          <span className="text-amber-600">未認証 — `huggingface-cli login`</span>
        )}
      </div>

      {!hub?.config && !editing && (
        <button onClick={() => setEditing(true)} className="text-blue-600">Configure Hub</button>
      )}

      {editing && (
        <div className="flex gap-2 items-end">
          <input
            placeholder="user/dataset_name"
            value={draft.repo_id}
            onChange={(e) => setDraft({ ...draft, repo_id: e.target.value })}
            className="border px-2 py-1 rounded"
          />
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={draft.private} onChange={(e) => setDraft({ ...draft, private: e.target.checked })} />
            Private
          </label>
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={draft.auto_push} onChange={(e) => setDraft({ ...draft, auto_push: e.target.checked })} />
            Auto-push
          </label>
          <button onClick={onSave} disabled={saving} className="bg-blue-600 text-white px-3 py-1 rounded">
            {saving ? "Saving…" : "Save"}
          </button>
          <button onClick={() => setEditing(false)} className="px-3 py-1">Cancel</button>
        </div>
      )}

      {hub?.config && !editing && (
        <div className="space-y-1">
          <div>
            <code>{hub.config.repo_id}</code>
            {hub.config.private && <span className="ml-2 text-xs text-gray-500">(private)</span>}
            {hub.config.auto_push && <span className="ml-2 text-xs text-blue-600">auto-push</span>}
            <button onClick={() => setEditing(true)} className="ml-2 text-xs text-blue-600">edit</button>
          </div>
          <div className="text-xs text-gray-600">
            {hub.state?.last_pushed_commit_sha ? (
              hub.state.last_pushed_manifest_hash
                ? `✓ Synced (commit ${hub.state.last_pushed_commit_sha.slice(0, 7)})`
                : `⚠ Pushed but stale (commit ${hub.state.last_pushed_commit_sha.slice(0, 7)})`
            ) : "Not pushed yet"}
          </div>
          <div>
            <button onClick={onPush}
                    disabled={!auth?.authenticated || pushing || hub.progress.status === "uploading" || hub.progress.status === "queued"}
                    className="bg-blue-600 text-white px-3 py-1 rounded disabled:opacity-50">
              {hub.progress.status === "uploading" ? "Uploading…" : "Push to HF Hub"}
            </button>
            {hub.progress.status === "uploading" && hub.progress.started_at && (
              <span className="ml-2 text-xs text-gray-500">
                started {new Date(hub.progress.started_at).toLocaleTimeString()}
              </span>
            )}
          </div>
          {hub.state?.last_push_error && (
            <div className="text-xs text-red-600">last error: {hub.state.last_push_error}</div>
          )}
          {error && <div className="text-xs text-red-600">{error}</div>}
        </div>
      )}
    </div>
  );
}
```

`DatasetsPage.tsx` の dataset 一覧描画箇所で各 dataset 行の中に `<HubSection ds={ds.name} />` を差し込む（既存の `{ds.name}` などを表示している `<div>` の末尾に追加）。

- [ ] **Step 2: 型チェック + ビルドが通ることを確認**

```bash
cd frontend && pnpm exec tsc --noEmit && pnpm build
```

期待: エラーなし。

- [ ] **Step 3: 手動動作確認**

```bash
bash scripts/run.sh
# 別ターミナルで:
# - http://localhost:5173 を開く
# - Datasets タブ
# - Hub セクションが表示される、Configure Hub → repo 入力 → Save できる
# - Push ボタン押下で進捗が出る（mock の場合は HF が無いので error になる）
```

- [ ] **Step 4: コミット**

```bash
git add frontend/src/pages/DatasetsPage.tsx
git commit -m "feat(frontend): Hub section in DatasetsPage with config + push button"
```

---

## Task 22: Integration test — snapshot consistency

**Files:**
- Create: `tests/integration/test_snapshot_consistency.py`

- [ ] **Step 1: テストを書く**

```python
from __future__ import annotations
import json
import os
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicrec.cloud.snapshot import make_push_snapshot, cleanup_snapshot
from mimicrec.cloud.hub_meta import compute_manifest_hash, write_hub_meta, HubMeta
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.metadata import append_episode, tombstone_episode
from mimicrec.recording.atomic_io import _atomic_write_text


def _seed(tmp_path: Path) -> Path:
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j0"], camera_names=["front"])
    for i in range(2):
        pq.write_table(
            pa.table({"frame_index": [0], "episode_index": [i],
                      "action": [[0.0]], "observation.state": [[0.0]],
                      "timestamp": [0.0], "index": [i], "task_index": [0]}),
            ds / "data" / "chunk-000" / f"episode_{i:06d}.parquet",
        )
        (ds / "videos" / "observation.images.front" / "chunk-000").mkdir(parents=True, exist_ok=True)
        (ds / "videos" / "observation.images.front" / "chunk-000" / f"episode_{i:06d}.mp4").write_bytes(b"\x00")
        append_episode(ds / "meta", {"episode_index": i, "task": "t",
                                     "num_frames": 1, "duration_sec": 0.1, "cameras": ["front"]})
    return ds


def test_snapshot_inode_frozen_after_atomic_replace(tmp_path: Path):
    ds = _seed(tmp_path)
    snap = make_push_snapshot(ds)
    try:
        snap_info = (snap / "meta" / "info.json").stat()
        # 原本側を atomic 書き換え
        _atomic_write_text(ds / "meta" / "info.json", json.dumps({"changed": True}))
        # snapshot 側 inode は変わらない
        snap_info_after = (snap / "meta" / "info.json").stat()
        assert snap_info.st_ino == snap_info_after.st_ino
        # 内容も古いまま
        snap_content = json.loads((snap / "meta" / "info.json").read_text())
        assert "changed" not in snap_content
    finally:
        cleanup_snapshot(snap)


def test_dirty_when_save_runs_during_push(tmp_path: Path):
    ds = _seed(tmp_path, n_eps := 1)
    start_hash = compute_manifest_hash(ds)
    snap = make_push_snapshot(ds)
    try:
        # snapshot 後に新しい episode を追加
        append_episode(ds / "meta", {"episode_index": 99, "task": "t",
                                     "num_frames": 1, "duration_sec": 0.1, "cameras": []})
        end_hash = compute_manifest_hash(ds)
        assert start_hash != end_hash   # → dirty
    finally:
        cleanup_snapshot(snap)


def test_snapshot_excludes_ignored_dirs(tmp_path: Path):
    ds = _seed(tmp_path)
    (ds / ".pending").mkdir(exist_ok=True)
    (ds / ".pending" / "junk").write_bytes(b"x")
    (ds / ".cache").mkdir(exist_ok=True)
    (ds / ".cache" / "blob").write_bytes(b"x")
    write_hub_meta(ds, HubMeta(repo_id="u/d"))
    snap = make_push_snapshot(ds)
    try:
        assert not (snap / ".pending").exists()
        assert not (snap / ".cache").exists()
        # meta/hub.json は ignore_patterns で upload 対象外（snapshot には残してよい）
    finally:
        cleanup_snapshot(snap)
```

- [ ] **Step 2: 実行**

```bash
bash scripts/test.sh tests/integration/test_snapshot_consistency.py -v
```

期待: 3 件 pass（既に Task 10 までで実装済み）。

- [ ] **Step 3: コミット**

```bash
git add tests/integration/test_snapshot_consistency.py
git commit -m "test(integration): snapshot consistency under concurrent saves"
```

---

## Task 23: Integration test — tombstone Hub cleanup

**Files:**
- Create: `tests/integration/test_tombstone_hub_cleanup.py`

- [ ] **Step 1: テスト**

```python
from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.cloud.hf_pusher import push_dataset
from mimicrec.cloud.snapshot import make_push_snapshot, cleanup_snapshot, collect_tombstoned_files
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.metadata import append_episode, tombstone_episode


def _seed(tmp_path: Path) -> Path:
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j0"], camera_names=["front"])
    for i in range(2):
        pq.write_table(
            pa.table({"frame_index": [0], "episode_index": [i],
                      "action": [[0.0]], "observation.state": [[0.0]],
                      "timestamp": [0.0], "index": [i], "task_index": [0]}),
            ds / "data" / "chunk-000" / f"episode_{i:06d}.parquet",
        )
        (ds / "videos" / "observation.images.front" / "chunk-000").mkdir(parents=True, exist_ok=True)
        (ds / "videos" / "observation.images.front" / "chunk-000" / f"episode_{i:06d}.mp4").write_bytes(b"\x00")
        append_episode(ds / "meta", {"episode_index": i, "task": "t",
                                     "num_frames": 1, "duration_sec": 0.1, "cameras": ["front"]})
    return ds


def test_push_after_tombstone_calls_delete_files(tmp_path):
    ds = _seed(tmp_path)
    tombstone_episode(ds / "meta", episode_index=0, deleted_at_unix=1234567890)
    tombstoned = collect_tombstoned_files(ds)
    assert "data/chunk-000/episode_000000.parquet" in tombstoned
    snap = make_push_snapshot(ds)
    try:
        api = MagicMock()
        api.list_repo_commits.side_effect = [
            [MagicMock(commit_id="up_sha")],
            [MagicMock(commit_id="del_sha")],
        ]
        with patch("mimicrec.cloud.hf_pusher.HfApi", return_value=api):
            result = push_dataset(snap, "u/d", private=True, tombstoned_files=tombstoned)
        api.delete_files.assert_called_once()
        # parent_commit が upload commit
        kw = api.delete_files.call_args.kwargs
        assert kw["parent_commit"] == "up_sha"
        assert "data/chunk-000/episode_000000.parquet" in kw["delete_patterns"]
        # 最終 commit_sha が delete commit
        assert result.commit_sha == "del_sha"
    finally:
        cleanup_snapshot(snap)
```

- [ ] **Step 2: pass**

```bash
bash scripts/test.sh tests/integration/test_tombstone_hub_cleanup.py -v
```

- [ ] **Step 3: コミット**

```bash
git add tests/integration/test_tombstone_hub_cleanup.py
git commit -m "test(integration): tombstone hub orphan cleanup via delete_files"
```

---

## Task 24: Integration test — atomic save under contention

**Files:**
- Create: `tests/integration/test_atomic_save.py`

- [ ] **Step 1: テスト**

```python
from __future__ import annotations
from pathlib import Path
import threading

import pyarrow.parquet as pq

from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.metadata import append_episode


def test_concurrent_reader_never_sees_partial(tmp_path: Path):
    init_dataset(tmp_path / "ds", fps=30, joint_names=["j0"], camera_names=[])
    ds = tmp_path / "ds"
    eps_pq = ds / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    stop = threading.Event()
    errors: list[str] = []

    def writer():
        for i in range(50):
            if stop.is_set():
                return
            try:
                append_episode(ds / "meta", {"episode_index": i, "task": "t",
                                             "num_frames": 1, "duration_sec": 0.1, "cameras": []})
            except Exception as e:
                errors.append(f"writer: {e}")
                return

    def reader():
        for _ in range(200):
            if stop.is_set():
                return
            try:
                if eps_pq.exists():
                    pq.read_table(eps_pq)   # partial だと壊れて raise
            except Exception as e:
                errors.append(f"reader: {e}")
                return

    tw = threading.Thread(target=writer)
    tr = threading.Thread(target=reader)
    tw.start(); tr.start()
    tw.join(timeout=10); stop.set(); tr.join(timeout=2)
    assert not errors, errors
```

- [ ] **Step 2: pass**

```bash
bash scripts/test.sh tests/integration/test_atomic_save.py -v
```

- [ ] **Step 3: コミット**

```bash
git add tests/integration/test_atomic_save.py
git commit -m "test(integration): concurrent reader sees no partial parquet"
```

---

## Task 25: Live HF push test (opt-in)

**Files:**
- Create: `tests/live/__init__.py`
- Create: `tests/live/test_hf_live_push.py`

- [ ] **Step 1: テスト**

```python
from __future__ import annotations
import os
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicrec.cloud.hf_pusher import push_dataset
from mimicrec.cloud.snapshot import make_push_snapshot, cleanup_snapshot
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.metadata import append_episode


pytestmark = pytest.mark.skipif(
    not os.environ.get("HF_TOKEN"),
    reason="HF_TOKEN not set; skipping live HF push test",
)


def _seed(tmp_path: Path) -> Path:
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j0"], camera_names=[])
    pq.write_table(
        pa.table({"frame_index": [0], "episode_index": [0],
                  "action": [[0.0]], "observation.state": [[0.0]],
                  "timestamp": [0.0], "index": [0], "task_index": [0]}),
        ds / "data" / "chunk-000" / "episode_000000.parquet",
    )
    append_episode(ds / "meta", {"episode_index": 0, "task": "t",
                                 "num_frames": 1, "duration_sec": 0.1, "cameras": []})
    return ds


def test_live_round_trip(tmp_path: Path):
    """Push to a temporary repo and verify it shows up on HF Hub. Cleans up the repo at the end."""
    from huggingface_hub import HfApi
    api = HfApi(token=os.environ["HF_TOKEN"])
    who = api.whoami()
    user = who["name"] if isinstance(who, dict) else who.name
    repo_id = f"{user}/mimicrec_test_{int(time.time())}"

    ds = _seed(tmp_path)
    snap = make_push_snapshot(ds)
    try:
        result = push_dataset(snap, repo_id, private=True)
        assert result.commit_sha
        # HF 側に居ることを確認
        info = api.repo_info(repo_id, repo_type="dataset")
        assert info is not None
    finally:
        cleanup_snapshot(snap)
        try:
            api.delete_repo(repo_id, repo_type="dataset")
        except Exception:
            pass
```

- [ ] **Step 2: 実行（HF_TOKEN ある時のみ）**

```bash
HF_TOKEN=... bash scripts/test.sh tests/live/test_hf_live_push.py -v
# 無しの環境では skipped 表示になる
bash scripts/test.sh tests/live/test_hf_live_push.py -v
```

期待: token 無し環境で skip、ある環境で pass。

- [ ] **Step 3: コミット**

```bash
git add tests/live/
git commit -m "test(live): opt-in HF Hub push round-trip with HF_TOKEN env"
```

---

## Task 26: 全テスト + smoke 確認 + lint 系

- [ ] **Step 1: 全テスト実行**

```bash
bash scripts/test.sh tests/ -q
```

期待: 全件 pass（live は HF_TOKEN 無ければ skip）。

- [ ] **Step 2: 既存テスト（recording / api）の回帰確認**

```bash
bash scripts/test.sh tests/unit/ tests/api/ tests/integration/ -v
```

期待: 全件 pass。

- [ ] **Step 3: dev サーバ smoke 起動**

```bash
bash scripts/run_backend.sh &
sleep 3
curl -s http://localhost:8000/api/cloud/auth-status | head -c 300
curl -s http://localhost:8000/api/datasets | head -c 300
kill %1
```

期待: 200 OK で JSON が返る。

- [ ] **Step 4: README に追記（オプション）**

`README.md` / `README.ja.md` の「対応ハードウェア」近辺、または「使い方」セクションに **HF Hub push** の項を 1 段落追加:

```
### 7. Hugging Face Hub に push する

`huggingface-cli login` でトークンを設定後、Datasets タブの「Configure Hub」から
`<user>/<dataset>` を入力。private がデフォルト。「Push to HF Hub」で push、
auto-push を ON にすると 1 episode save ごとに自動 push される。
```

- [ ] **Step 5: コミット**

```bash
git add README.md README.ja.md
git commit -m "docs: HF Hub push usage in README"
```

---

## Self-review checklist

実装完了後に以下を確認:

- [ ] **DoD 全項目**: spec の Definition of done 11 項目を 1 つずつテスト or 手動で確認
- [ ] **依存追加**: `huggingface_hub>=0.34` が `backend/pyproject.toml` に入っている
- [ ] **atomic 化 8 箇所** すべてが `_atomic_write_*` を使用している
- [ ] **lock 注入**: `append_episode` / `tombstone_episode` / `upsert_task` / `update_info_totals` / `save_annotations` / `PendingEpisode.save` が coordinator + ds_name を受ける
- [ ] **API ステータスコード順**: path → 存在 → auth → 設定 → 重複（手動 push）
- [ ] **DELETE /datasets/{ds}** が in_flight を見て 409、または lock を取って削除し coordinator を cleanup
- [ ] **snapshot ignore**: `.pending/`, `.cache/`, `.git/` 全てカバー
- [ ] **symlink 検出**: 検出時に `SnapshotError`、push が `last_push_error` に永続化される
- [ ] **dirty 判定 3 状態**: 未 push / clean / dirty が UI に正しく表示
- [ ] **auto-push** が thread executor から `call_soon_threadsafe` で event loop に乗る
- [ ] **orphan snapshot** が起動時に消える
- [ ] **safe_dataset_path** が新規ルート + DELETE /datasets/{ds} に適用
- [ ] **frontend** が build 通る、handler が正しく polling
- [ ] **live test** が `HF_TOKEN` 有時のみ実行される（CI で skip）

各項目に該当する test/integration/manual を spec の DoD と突き合わせる。

---

## Notes for the implementer

- **lerobot 公式の `LeRobotDataset.push_to_hub` は使わない**（spec で意思決定済）。`huggingface_hub.HfApi` を直接呼ぶ
- **`upload_large_folder` は値を返さない**ので必ず `list_repo_commits()[0].commit_id` で commit sha を取り直す
- **`asyncio.shield` 配下の thread はキャンセルできない**ので `await inner` を必ず追加で待つ
- **`threading.RLock`** を使う（同 thread の再入を許す）。`append_episode` → `update_info_totals` のネスト呼びがある
- **path traversal 対策**は本 PR では新規ルート + DELETE のみ。既存 datasets.py の他ルートへの拡張は別 PR
- **multi-machine** は v1 では single-machine 前提。複数マシン同時 push の調停は scope 外
- **dataset 内 symlink は禁止**（snapshot で検出して fail）
- **fsync は v1 では入れない**（partial-read 防止のみが要件）
