# Hugging Face Hub push integration — design

## Problem

MimicRec で録ったデータセットは現状 `datasets/<name>/` 以下にしかなく、別マシンや学習環境で使うには手動でコピーする必要がある。LeRobot v3 形式は HF Hub と相性が良く、`LeRobotDataset.from_pretrained("user/name")` で 1 行ロードできる利点がある。

これを生かし、**録画したデータセットを Hugging Face Hub の private dataset repo に push する機能** を追加したい。バックアップ・他マシンからの利用・将来的な配布の起点になる。

ただし MimicRec は録画中も応答しなければならず、push 中も recording loop と meta 更新は走り続けるため、単純に upload するだけでは **複数ファイルにわたる dataset-level の不整合**を Hub に晒す。録画コードの atomicity を整えた上で、push 専用に **hardlink snapshot** を切って upload する設計にする。

## Goals

1. 既存 `datasets/<name>/` をフォーマット変換せず、**LeRobot v3 native のまま** HF Hub に push できる。
2. **手動 push**（UI のボタン）と **データセット単位の auto-push**（episode save 後）を両方サポート。
3. **HF 認証は `huggingface-cli login` のキャッシュトークン**を再利用し、コード側でトークンを保持しない。
4. 数 GB 級のデータでも **バックグラウンド実行・再開可能**で、UI が固まらない。
5. push 中も **recording を止めない**（dataset の atomicity を担保した上で、hardlink snapshot から push）。
6. **デフォルト private** で、UI/API/スキーマすべての層で `private=true` をデフォルトにする。
7. push 失敗は永続化され、プロセス再起動後も最後の失敗が UI に表示される。
8. **同一 dataset の push 多重起動を確実に 1 本に絞る**（手動連打・auto-push 競合）。
9. 録画 / metadata 更新 / snapshot / push の **競合状態を仕様で説明できる**（race window がない）。

## Definition of done

- [ ] `huggingface-cli login` 済みの環境で UI から「Push to HF Hub」ボタンを押すと、対象 dataset の `meta/info.json` / `data/` / `videos/` が指定 repo に private dataset としてアップロードされる。
- [ ] 同じ操作後、別マシンで `LeRobotDataset.from_pretrained("<user>/<name>")` が成功する（手動検証）。
- [ ] dataset 設定で `auto_push=true` にした状態で 1 episode を録画 → save 後に push が自動でエンキューされ、`status` が `uploading` → `done` に遷移する。
- [ ] 同じ dataset の `POST /hub/push` を**連続 5 回叩いても**、走るタスクは **1 本だけ**で残りは 409。
- [ ] `huggingface-cli login` していない状態で push を叩くと **401**、UI には「`huggingface-cli login` してください」と出る。
- [ ] 2.9GB 級の dataset でも push 中に UI が固まらず、進捗バー（spinner + 経過時間 + status 文字列）が更新される。
- [ ] push 中に新しい episode が save() されても、**push 対象には反映されず**（snapshot 凍結）、push 完了後の `last_pushed_manifest_hash` が dirty として記録される。
- [ ] push 中に SIGKILL → 再起動 → `meta/hub.json` から最後の `last_push_error` が UI に復元される（成功してたなら `last_pushed_commit_sha` が残る）。
- [ ] dataset 配下のメタ書き込み 8 箇所（後述）が **partial-read 不能** になっている（temp + `os.replace` で原子的）。
- [ ] tombstone した episode の parquet/mp4 が、次の push 後に Hub 側からも削除される。
- [ ] tests: unit (`hf_pusher`, `hub_meta`, `atomic_io`, `snapshot`), API (`/hub/*`), integration (録画 → save → auto-push が enqueue される)、HF live test は `HF_TOKEN` env 有時のみ実行。

## Non-goals (Out of scope)

- **Multi-machine の同時 push 調停**。v1 は **single-machine 前提**。複数マシンが同じ repo に push したら commit 順は HF 側に任せ、conflict 検出はしない（branch + PR モデルは v2 以降）。
- **lerobot の `LeRobotDataset.push_to_hub` 利用**。`LeRobotDataset` のコンストラクタは Hub と双方向同期するなど副作用が大きいため、`huggingface_hub.HfApi` を直接使う。
- **データセットカード（README.md）自動生成**。必要になれば後続 PR で。
- **HF → ローカルの pull / sync 方向**。push のみ。
- **VLA-compat 形式での push**。LeRobot v3 native のみ。VLA-compat は既存の `export_dataset_to_local` で別途。
- **複数 dataset の同時 push**。v1 は許容するが、最適化はしない（独立 repo なので干渉なし）。
- **push のキャンセル API**。v1 では作らない。push が始まったら完了か失敗まで走る。
- **uvicorn の multi-worker 対応**。v1 は **single process**（uvicorn `--workers 1`）前提。多 worker は scope 外。
- **dataset 内 symlink**。snapshot 作成時に検出して **fail**（v1 では禁止）。
- **電源断耐性のための fsync**。partial-read 防止のみ要件、クラッシュ後 tmp file が残るのは許容（best-effort cleanup）。
- **tombstone した episode の Hub 側 commit history からの抹消**。新 commit で `delete_files` するだけで、古い revision には残る（HF Hub の git 仕様）。

## Decisions summary

| 項目 | 決定 | 補足 |
|---|---|---|
| Push 先 | Hugging Face Hub private dataset repo | repo 命名は `<user-or-org>/<dataset-slug>` |
| フォーマット | LeRobot v3 native | 変換なし、`datasets/<name>/` をそのまま |
| 認証 | `huggingface-cli login` のキャッシュ | コード側はトークンを触らない、`HfApi()` が暗黙に拾う |
| Push API | `huggingface_hub.HfApi.upload_large_folder` | resumable / multi-thread / per-task retry |
| 戻り値 | `upload_large_folder` は値を返さない → `list_repo_commits()[0].commit_id` で取り直す | `CommitInfo.oid` 属性は使わない |
| Tombstone 削除 | upload 完了後に `HfApi.delete_files(parent_commit=upload_sha)` で別 commit | `upload_large_folder` は upload 中の delete 不可 |
| 手動 / 自動 | 両方 | UI ボタン（手動）+ dataset 単位の `auto_push` toggle |
| Auto-push トリガ | `PendingEpisode.save()` 完了直後 | thread executor から `loop.call_soon_threadsafe()` で event loop に投げる |
| 同時実行制御 | dataset 名で 1 in-flight | `coordinator.in_flight: set[str]` を `threading.Lock` で守る |
| キャンセル | API なし | shield で `CancelledError` を握る、thread 完了を必ず待ってから `meta/hub.json` を書く |
| メタ保存先 | **`meta/hub.json` に分離** | `info.json` の lost update を避ける |
| ローカル dirty 判定 | `path + size + mtime_ns` の sha256 | start_hash / end_hash を save_lock 内で取り、一致時のみ clean マーク |
| Atomic write | `recording/atomic_io.py` 新設、tmp は `NamedTemporaryFile(dir=parent, delete=False)` | 全 dataset 配下メタ書き込みを `os.replace` で原子化 |
| Snapshot 方式 | `shutil.copytree(copy_function=os.link)` で hardlink-copy → tombstoned episode 由来の data/video file を削除 → `episodes.parquet` と `info.json` を deleted 除外で再生成 | `.pending/`, `.cache/`, `.git/` を ignore、symlink 検出時は fail |
| Push 時 lock | snapshot 作成時のみ短く `save_lock` を取る、upload 本体は no-lock | dataset-level 整合は snapshot 凍結で担保 |
| Lock 種別 | `threading.RLock`（再入可） | `append_episode → update_info_totals` のような同 thread 内ネスト呼び出しを許す |
| dataset 内書込み参加者 | save / tombstone / upsert_task / annotate / dataset 削除 | 全部 `save_lock` 経由 + atomic write |
| Private デフォルト | UI / API / スキーマ層で **true 固定** | API は明示的 `false` 指定で初めて public |
| 認証ステータスキャッシュ | 60 秒 TTL、`?refresh=1` で強制 | `whoami` が遅い+offline の救済 |
| 進捗 UI | 既存 `annotate_progress` パターン踏襲 | 2 秒間隔ポーリング、SSE は v2 |
| 進捗の細かさ | spinner + 経過時間 + status 文字列 | `upload_large_folder` には詳細 callback がないため |
| dataset 名検証 | 共通ヘルパー `safe_dataset_path()` | `.resolve().is_relative_to(root.resolve())` を強制 |

## Architecture

```
Frontend (React)
    └─ DatasetDetail / Hub section
        ├─ GET /api/cloud/auth-status        (60s TTL cache)
        ├─ GET /api/datasets/{ds}/hub        (poll 2s)
        ├─ PUT /api/datasets/{ds}/hub        (config save)
        └─ POST /api/datasets/{ds}/hub/push  (202 + bg task)

Backend (FastAPI + asyncio)
    ├─ api/routes/cloud.py            ← 新ルート群
    ├─ cloud/
    │   ├─ hf_pusher.py               ← HfApi 呼び出し（同期、to_thread で分離）
    │   ├─ hub_meta.py                ← meta/hub.json 読み書き
    │   ├─ snapshot.py                ← hardlink snapshot make/cleanup
    │   └─ push_state.py              ← PushCoordinator（in_flight / save_locks / progress）
    └─ recording/
        ├─ atomic_io.py               ← 新設、_atomic_write_parquet / _atomic_write_text
        ├─ pending.py                 ← save() を atomic 化、save_lock 参加、auto-push 発火
        ├─ metadata.py                ← append_episode / tombstone / upsert_task / update_info_totals を atomic 化 + lock 参加
        └─ dataset_layout.py          ← init_dataset を atomic 化 + mkdir(exist_ok=False)
    └─ annotator/
        └─ subtask.py                 ← annotate save を atomic 化 + lock 参加
```

## Components

### `backend/mimicrec/cloud/hf_pusher.py`

```python
@dataclass(frozen=True)
class PushResult:
    commit_sha: str
    repo_id: str

def push_dataset(
    src: Path,                          # snapshot dir（ds_root ではない）
    repo_id: str,
    *,
    private: bool,
    tombstoned_files: list[str] | None = None,
) -> PushResult:
    api = HfApi()
    api.create_repo(repo_id, repo_type="dataset", private=private, exist_ok=True)
    api.upload_large_folder(
        folder_path=str(src),
        repo_id=repo_id,
        repo_type="dataset",
        private=private,
        ignore_patterns=[
            ".pending/**", ".pending/",
            ".cache/**", "cache/huggingface/**",
            ".git/**", ".git",
            "meta/hub.json",
        ],
        print_report=False,
    )
    commits = api.list_repo_commits(repo_id=repo_id, repo_type="dataset")
    head_sha = commits[0].commit_id

    if tombstoned_files:
        api.delete_files(
            repo_id=repo_id, repo_type="dataset",
            delete_patterns=tombstoned_files,
            commit_message="cleanup tombstoned episodes",
            parent_commit=head_sha,
        )
        commits = api.list_repo_commits(repo_id=repo_id, repo_type="dataset")
        head_sha = commits[0].commit_id

    return PushResult(commit_sha=head_sha, repo_id=repo_id)
```

### `backend/mimicrec/cloud/hub_meta.py`

```python
@dataclass
class HubMeta:
    repo_id: str
    private: bool = True
    auto_push: bool = False
    last_pushed_at: str | None = None
    last_pushed_commit_sha: str | None = None
    last_pushed_manifest_hash: str | None = None  # path+size+mtime_ns sha256, dirty 判定
    last_push_error: str | None = None

def hub_meta_path(ds_root: Path) -> Path:
    return ds_root / "meta" / "hub.json"

def read_hub_meta(ds_root: Path) -> HubMeta | None:
    p = hub_meta_path(ds_root)
    if not p.exists():
        return None
    return HubMeta(**json.loads(p.read_text()))

def write_hub_meta(ds_root: Path, meta: HubMeta) -> None:
    """Atomic via tmp + os.replace."""
    _atomic_write_text(hub_meta_path(ds_root), json.dumps(asdict(meta), indent=2))

def compute_manifest_hash(ds_root: Path) -> str:
    """sha256 of sorted (relative_path, size, mtime_ns) tuples for push-target files.
    .pending/, .cache/, .git/, meta/hub.json は除外（ignore と同集合）。"""
```

### `backend/mimicrec/cloud/snapshot.py`

```python
SNAPSHOT_IGNORE = (".pending", ".cache", ".git")

def detect_symlinks(ds_root: Path) -> list[Path]:
    """Recursively find symlinks under ds_root (excluding ignored dirs)."""

def make_push_snapshot(ds_root: Path) -> Path:
    """Hardlink-copy ds_root to a sibling dir for push isolation, then strip
    tombstoned episodes from the snapshot. Caller must hold the save_lock
    during this call (this function does NOT acquire the lock itself)."""
    syms = detect_symlinks(ds_root)
    if syms:
        raise SnapshotError(f"dataset contains symlinks (forbidden in v1): {syms}")
    snapshot = ds_root.parent / f".push-snapshot-{ds_root.name}-{uuid4().hex[:8]}"
    def _ignore(_dir, names):
        return [n for n in names if n in SNAPSHOT_IGNORE]
    shutil.copytree(ds_root, snapshot, copy_function=os.link, ignore=_ignore,
                    dirs_exist_ok=False, symlinks=False)
    _strip_tombstoned(snapshot)   # see below
    return snapshot

def _strip_tombstoned(snapshot: Path) -> None:
    """Remove tombstoned episode data/video files and rewrite episodes.parquet
    + info.json to exclude deleted rows. Breaks hardlinks for those files in
    the snapshot only (original ds_root inodes remain intact)."""
    meta_dir = snapshot / "meta"
    rows = pq.read_table(meta_dir / "episodes" / "chunk-000" / "file-000.parquet").to_pylist()
    deleted = [r for r in rows if r.get("deleted")]
    if not deleted:
        return
    # 1) hardlink を解除する形で data/mp4 を unlink（refcount--、original ds_root は無傷）
    for row in deleted:
        ep_idx = row["episode_index"]
        chunk = ep_idx // 1000
        for p in (snapshot / "data" / f"chunk-{chunk:03d}" / f"episode_{ep_idx:06d}.parquet",):
            p.unlink(missing_ok=True)
        videos_dir = snapshot / "videos"
        if videos_dir.exists():
            for cam_dir in videos_dir.iterdir():
                vp = cam_dir / f"chunk-{chunk:03d}" / f"episode_{ep_idx:06d}.mp4"
                vp.unlink(missing_ok=True)
    # 2) episodes.parquet を deleted 除外で再生成（dataset_from/to_index 再計算）
    kept = [r for r in rows if not r.get("deleted")]
    offset = 0
    for r in sorted(kept, key=lambda x: x["episode_index"]):
        r["dataset_from_index"] = offset
        r["dataset_to_index"] = offset + r.get("length", 0)
        offset = r["dataset_to_index"]
    _atomic_write_parquet(pa.Table.from_pylist(kept),
                          meta_dir / "episodes" / "chunk-000" / "file-000.parquet")
    # 3) info.json の totals を再計算
    info = json.loads((meta_dir / "info.json").read_text())
    info["total_episodes"] = len(kept)
    info["total_frames"] = sum(r.get("length", 0) for r in kept)
    info["splits"] = {"train": f"0:{len(kept)}"}
    _atomic_write_text(meta_dir / "info.json", json.dumps(info, indent=2))

def collect_tombstoned_files(ds_root: Path) -> list[str]:
    """List Hub-relative paths to delete via post-upload delete_files. Includes
    files that were pushed in a previous revision but are now tombstoned (i.e.,
    they need cleanup on the Hub side, since upload_large_folder does NOT delete
    files missing from the source)."""

def cleanup_snapshot(snapshot: Path) -> None:
    if snapshot.exists() and snapshot.name.startswith(".push-snapshot-"):
        shutil.rmtree(snapshot)
```

### `backend/mimicrec/cloud/push_state.py`

```python
@dataclass
class PushProgress:
    status: Literal["idle", "queued", "uploading", "done", "error"] = "idle"
    started_at: str | None = None
    ended_at: str | None = None
    error: str | None = None
    repo_id: str | None = None
    last_pushed_commit_sha: str | None = None

class PushCoordinator:
    """Per-process state. v1 single-process only."""
    def __init__(self):
        self._mu = threading.Lock()       # in_flight / save_locks の dict 操作を守る
        self.in_flight: set[str] = set()
        self.save_locks: dict[str, threading.RLock] = {}
        self.progress: dict[str, PushProgress] = {}

    def get_save_lock(self, ds_name: str) -> threading.RLock:
        """Returns a re-entrant lock so that nested writer calls
        (e.g. append_episode → update_info_totals) on the same thread don't deadlock."""
        with self._mu:
            return self.save_locks.setdefault(ds_name, threading.RLock())

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
```

### `backend/mimicrec/recording/atomic_io.py`

```python
import os, tempfile
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

def _atomic_write_parquet(table: pa.Table, dst: Path) -> None:
    parent = dst.parent
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=dst.name + ".", suffix=".tmp", dir=parent, delete=False
    ) as f:
        tmp = Path(f.name)
    try:
        pq.write_table(table, tmp)
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

def _atomic_write_text(path: Path, content: str) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=path.name + ".", suffix=".tmp", dir=parent, delete=False, mode="w"
    ) as f:
        f.write(content)
        tmp = Path(f.name)
    try:
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
```

## Data flow

### 認証ステータス

```
GET /api/cloud/auth-status?refresh=0
  ├─ app.state.auth_cache が 60s 以内 → そのまま返す
  └─ 古い or refresh=1 → HfApi().get_token() で token 有無確認
                          token あり → HfApi(token=...).whoami() で username 取得（失敗は飲む）
                          結果を auth_cache に保存
```

`HfFolder.get_token()` は `huggingface_hub` の旧 API で、`>=0.34` では `HfApi().get_token()` が推奨されている（旧 API はまだ動くがスタブ化）。本 spec では `HfApi().get_token()` を **正規** とする。

### 手動 push

ステータスコードの優先順は **path → 存在 → 認証 → 設定 → 重複** の順:

```
POST /api/datasets/{ds}/hub/push
  ↓ route handler:
    1. safe_dataset_path(root, ds) で path traversal 防止 (400 if invalid)
    2. ds_root 存在チェック (404 if absent)
    3. HfApi().get_token() で token 確認 (401 if None)
    4. read_hub_meta(ds_root) で repo_id 取得 (400 "configure hub first" if None)
    5. coordinator.try_reserve(ds) → False なら 409 "push already in flight"
    6. progress[ds] = PushProgress(status="queued", repo_id, started_at=iso_now())
    7. asyncio.create_task(_run_push_with_release(ds))
    8. 202 Accepted（即返）

asyncio task _run_push_with_release(ds):
    try:
        await _push_task(ds)
    finally:
        coordinator.release(ds)

_push_task(ds_root, ds_name):
    save_lock = coordinator.get_save_lock(ds_name)
    progress[ds_name].status = "uploading"
    snap: Path | None = None
    meta: HubMeta | None = None
    tombstoned: list[str] = []
    start_hash: str | None = None
    setup_error: Exception | None = None

    # (a) snapshot 作成（save_lock 内で短時間）。失敗も全部 finalize で永続化する。
    def _take_snapshot():
        with save_lock:
            m = read_hub_meta(ds_root)
            t = collect_tombstoned_files(ds_root)
            sh = compute_manifest_hash(ds_root)
            s = make_push_snapshot(ds_root)
            return m, t, sh, s

    try:
        meta, tombstoned, start_hash, snap = await asyncio.to_thread(_take_snapshot)
    except Exception as e:
        # symlink 検出失敗 / hub.json 不在 / hash 計算失敗 など: snapshot 取れずに終わる。
        # finalize に委譲して last_push_error を必ず書く。
        setup_error = e
        await asyncio.to_thread(_finalize_with_error, ds_root, ds_name, e)
        return

    # (b) snapshot から push（lock 無し、long-running）
    inner = asyncio.create_task(asyncio.to_thread(
        push_dataset, snap, meta.repo_id,
        private=meta.private, tombstoned_files=tombstoned,
    ))
    result = None
    push_error = None
    try:
        result = await asyncio.shield(inner)
    except asyncio.CancelledError:
        try:
            result = await inner   # thread 完了を必ず待つ
        except Exception as e:
            push_error = e
    except Exception as e:
        push_error = e

    # (c) finalize（save_lock 内で metadata 更新 + cleanup）
    def _finalize():
        try:
            with save_lock:
                current = read_hub_meta(ds_root) or meta
                end_hash = compute_manifest_hash(ds_root)
                if push_error or result is None:
                    current.last_push_error = str(push_error) if push_error else "push aborted"
                    progress[ds_name].status = "error"
                    progress[ds_name].error = current.last_push_error
                else:
                    current.last_pushed_commit_sha = result.commit_sha
                    current.last_pushed_at = iso_now()
                    current.last_pushed_manifest_hash = start_hash if end_hash == start_hash else None
                    current.last_push_error = None
                    progress[ds_name].status = "done"
                    progress[ds_name].last_pushed_commit_sha = result.commit_sha
                progress[ds_name].ended_at = iso_now()
                write_hub_meta(ds_root, current)
        finally:
            if snap is not None:
                cleanup_snapshot(snap)

    await asyncio.to_thread(_finalize)


def _finalize_with_error(ds_root, ds_name, error: Exception) -> None:
    """Snapshot 段階で失敗したケース用の最低限 finalize（save_lock 内で実行）。"""
    save_lock = coordinator.get_save_lock(ds_name)
    with save_lock:
        existing = read_hub_meta(ds_root)
        if existing is not None:
            existing.last_push_error = str(error)
            write_hub_meta(ds_root, existing)
        progress[ds_name].status = "error"
        progress[ds_name].error = str(error)
        progress[ds_name].ended_at = iso_now()
```

### Auto-push

`PendingEpisode.save()` の最後（save_lock 解放後）で:

```python
def _maybe_trigger_auto_push(ds_root, ds_name, app_loop):
    meta = read_hub_meta(ds_root)   # read のみで save_lock 不要
    if meta is None or not meta.auto_push:
        return
    if not coordinator.try_reserve(ds_name):
        return  # 既に in-flight、または 連続 save の 2 回目以降
    # save() は thread executor で動いている可能性があるので、
    # event loop に schedule する。失敗時は in_flight を必ず戻す。
    coordinator.progress[ds_name] = PushProgress(
        status="queued", repo_id=meta.repo_id, started_at=iso_now()
    )
    try:
        app_loop.call_soon_threadsafe(
            lambda: asyncio.create_task(_run_push_with_release(ds_name))
        )
    except RuntimeError:
        # event loop が closed 等。reserve を戻す。
        coordinator.release(ds_name)
        coordinator.progress[ds_name].status = "error"
        coordinator.progress[ds_name].error = "event loop unavailable"
```

`SessionManager` 起動時に `app_loop = asyncio.get_running_loop()` を保持して `PendingEpisode` に注入する。

### Dataset 削除時の調停

```
DELETE /api/datasets/{ds}
  1. coordinator.in_flight に ds があるか? → あれば 409 "push in flight"
  2. coordinator.get_save_lock(ds) を取得（push 中の snapshot 取得を阻む）
  3. shutil.rmtree(ds_root)
  4. coordinator.save_locks / progress / in_flight から ds を pop（cleanup）
```

## Atomic write 8 箇所

| ファイル:行 | 関数 | 修正 |
|---|---|---|
| `recording/pending.py:113` | `PendingEpisode.save()` の data parquet 書き出し | `_atomic_write_parquet(table, dst)` |
| `recording/metadata.py:91` | `append_episode()` の episodes parquet | 同 |
| `recording/metadata.py:125` | `tombstone_episode()` の episodes parquet | 同 |
| `recording/metadata.py:142` | `upsert_task()` の tasks parquet | 同 |
| `recording/metadata.py:160` | `update_info_totals()` の info.json | `_atomic_write_text` |
| `recording/dataset_layout.py:107` | `init_dataset()` の info.json 初期化 | 同 |
| `recording/dataset_layout.py:117` | `init_dataset()` の tasks.parquet 初期化 | `_atomic_write_parquet` |
| `annotator/subtask.py:254` | `save_annotations()` が **episode data parquet を annotation 列付きで上書き**（subtasks 専用 parquet ではない） | `_atomic_write_parquet` |

加えて `init_dataset()` 自体の TOCTOU 修正:
- 現状: 呼び出し元で `if ds_root.exists()` チェック後 `mkdir(exist_ok=True)`
- 修正: `init_dataset` の最初に `ds_root.mkdir(parents=True, exist_ok=False)` を行い、既存 dataset 名 race を防ぐ。`FileExistsError` を呼び出し元で 409 にマップ。

## Lock 参加者と境界

`save_lock` は dataset 名でキー、**`threading.RLock`**（再入可）。以下の **書き込み関数の中** で取得する（呼び出し元任せにしない）:

- `PendingEpisode.save()` の rename + `append_episode` 連続部分
- `tombstone_episode()`
- `upsert_task()`
- `update_info_totals()`（`append_episode` / `tombstone_episode` から呼ばれる場合は同一 thread でのネスト取得 = RLock で許容）
- `save_annotations()`（annotator）

`make_push_snapshot()` 自身は **lock を取得しない**（caller の `_take_snapshot()` が `with save_lock:` で囲む）。

非同期側からは `await asyncio.to_thread(do_locked_work)` の形で「取得から解放まで同一 sync 関数内」に閉じる。

### Coordinator の注入

書き込み関数は dataset name と coordinator を知らないと lock を引けないため、**新規 kwargs を追加** する:

```python
def append_episode(meta_dir, row, *, coordinator: PushCoordinator, ds_name: str) -> None: ...
def tombstone_episode(meta_dir, idx, deleted_at_unix, *, coordinator, ds_name) -> None: ...
def upsert_task(meta_dir, task_name, instruction, *, coordinator, ds_name) -> None: ...
def update_info_totals(meta_dir, *, coordinator, ds_name) -> None: ...
def save_annotations(ds_root, idx, segments, *, coordinator, ds_name) -> None: ...
```

呼び出し元（route handler / `PendingEpisode.save()` / SessionManager / annotator）は `app.state.push_coordinator` を渡す。`ds_name` は呼び出し元の path から既知（`ds_root.name`）。

`PendingEpisode` は `__init__` で `coordinator` と `ds_name` を受け、`save()` 内部で lock を取得する。

## API endpoints

### `GET /api/cloud/auth-status[?refresh=1]`

```json
{
  "authenticated": true,
  "username": "TakakiMaeda",
  "checked_at": "2026-05-09T12:34:56Z"
}
```

token 不在時は `{"authenticated": false, "username": null, "checked_at": ...}`。

### `GET /api/datasets/{ds}/hub`

```json
{
  "config": {
    "repo_id": "TakakiMaeda/learn-data-bottle",
    "private": true,
    "auto_push": false
  },
  "state": {
    "last_pushed_at": "2026-05-09T...",
    "last_pushed_commit_sha": "abc123...",
    "last_pushed_manifest_hash": "sha256:...",
    "last_push_error": null
  },
  "progress": {
    "status": "uploading",
    "started_at": "2026-05-09T...",
    "ended_at": null,
    "error": null
  }
}
```

`hub.json` 不在時は `config`/`state` を `null` で返す（"not configured" シグナル）。

### `PUT /api/datasets/{ds}/hub`

Request:
```json
{
  "repo_id": "TakakiMaeda/learn-data-bottle",
  "private": true,
  "auto_push": false
}
```
- `repo_id` 必須、フォーマット検証（`^[\w-]+/[\w.-]+$`）
- `private` 省略時は `true`（**デフォルト private**）
- `auto_push` 省略時は `false`
- `meta/hub.json` を atomic write
- 既存値とマージし、`last_*` フィールドは保持

### `POST /api/datasets/{ds}/hub/push`

- 認証なし → 401
- hub 未設定 → 400
- 既に in-flight → 409
- それ以外 → 202 + バックグラウンド実行

### `DELETE /api/datasets/{ds}` の挙動変更

```
1. coordinator._mu の下で:
   - if ds in coordinator.in_flight: 409 を返す（push 中の削除を阻止）
   - 同時に「予約中の削除」を表すフラグを立てる（または in_flight に削除タスクを足す）
2. save_lock を取って shutil.rmtree(ds_root)
3. coordinator.save_locks / progress / in_flight から ds を pop（cleanup）
```

`push in-flight` の判定と「削除予約」を **同じ critical section** で行うことで、push 開始の競合と矛盾しない（push 側も `try_reserve` で同じ mutex を取る）。

### Dirty 判定の規約

`last_pushed_commit_sha` と `last_pushed_manifest_hash` の組で 3 状態を表現する:

| `last_pushed_commit_sha` | `last_pushed_manifest_hash` | 状態 | UI 表示 |
|---|---|---|---|
| `None` | `None` | **未 push** | "Not pushed yet" |
| `<sha>` | `<hash>` | **clean**（push 中に dataset 変化なし） | "✓ Synced (commit abc123)" |
| `<sha>` | `None` | **dirty during push**（push 中に save が走った） | "⚠ Pushed but stale (commit abc123)" |

frontend は **追加で `compute_manifest_hash(ds_root)` を呼ぶ必要なく**、保存済みの 2 フィールドだけで判定できる。「現在も clean か」を確認したい場合は backend に `GET /api/datasets/{ds}/hub` を投げ直せば最新 hub.json が返る（push 後に save が走ったかは `last_pushed_manifest_hash == None` で示される）。

## Frontend changes

`frontend/src/api/cloud.ts` を新設:
```ts
export async function getAuthStatus(refresh = false): Promise<AuthStatus>;
export async function getHub(ds: string): Promise<HubResponse>;
export async function putHub(ds: string, body: HubConfig): Promise<HubResponse>;
export async function postPush(ds: string): Promise<{ status: "queued" }>;
```

`frontend/src/pages/DatasetDetail.tsx`（または既存 Settings の dataset セクション）に **Hub セクション** を追加:
- 認証バッジ（`@username` で認証済み / 未認証）
- repo_id 入力 + private トグル + auto-push トグル
- "Push to HF Hub" ボタン
- 進捗バー: status に応じて `idle | queued | uploading (経過時間) | done (commit sha 短縮) | error (メッセージ)`
- TanStack Query で `getHub` を 2 秒間隔ポーリング、`status === "uploading"` の間だけ refetchInterval を有効化

## Test plan

### Unit
- `tests/cloud/test_atomic_io.py`: tmp 経由で書き、kill 中（途中 raise）でも dst が無傷
- `tests/cloud/test_hub_meta.py`: read/write/round-trip、欠損フィールドのデフォルト
- `tests/cloud/test_snapshot.py`: hardlink で同 inode、ignore（`.pending/` 等）が除外、symlink 検出で fail
- `tests/cloud/test_hf_pusher.py`: `HfApi` をモック、create_repo + upload_large_folder + list_repo_commits + delete_files 呼出順、ignore_patterns に `.pending`/`meta/hub.json` 含有
- `tests/cloud/test_push_state.py`: try_reserve / release が thread-safe（同時実行で 1 つだけ通る）

### API
- `tests/api/test_cloud_routes.py`:
  - 認証なしで `POST /push` → 401
  - hub 未設定で `POST /push` → 400
  - 同 ds への二重 `POST /push` → 二回目 409
  - 異なる ds の同時 push → 両方 202
  - `PUT /hub` で `private` 省略 → `true` で保存
  - `DELETE /datasets/{ds}` push 中 → 409

### Integration
- `tests/integration/test_atomic_save.py`: save() 中に並行 reader が partial を読まない（atomic 化検証）
- `tests/integration/test_auto_push_flow.py`: mock `HfApi`、auto_push=true で 1 episode save → push が enqueue される
- `tests/integration/test_snapshot_consistency.py`:
  - snapshot 直後の hardlink 検証（`os.stat().st_ino` と `st_nlink` で同 inode・refcount=2）
  - snapshot 後に `os.replace` で原本 `info.json` を書き換え → snapshot 側 `info.json` の inode/content が変わらない
  - `start_hash != end_hash` のとき `last_pushed_manifest_hash = None`（dirty）
  - tombstoned episode を含む snapshot で、deleted file が unlink され、`episodes.parquet` から row が除外され、`info.json` の totals が再計算される
  - dataset 内 symlink を仕込むと `make_push_snapshot()` が `SnapshotError` を投げる
  - snapshot に `meta/hub.json` が含まれず、ignore patterns（`.pending/`, `.cache/`, `.git/`）も含まれない
- `tests/integration/test_tombstone_hub_cleanup.py`: 一度 push → episode 削除 → 再 push → snapshot に該当 file 不在、`delete_files(parent_commit=...)` が呼ばれる

### Live (opt-in)
- `tests/live/test_hf_live_push.py`: `HF_TOKEN` 環境変数があるときのみ実行、`mimicrec_test_<random>` repo を作って push → `from_pretrained` で読めるか確認 → 削除

## Migration / backwards compatibility

- 既存 dataset には `meta/hub.json` が無い。これは「未設定」状態として UI に「Configure Hub」と出す。`PUT /hub` で初めて作成。
- 既存の non-atomic な `info.json` / parquet は影響なし（atomic 化は **書き込みパス**だけ変更、ファイル形式は同じ）。
- `init_dataset` の `mkdir(exist_ok=False)` 化: 既存 ds との衝突は呼び出し元の事前チェックがすでにあるので実害なし。`FileExistsError` は呼び出し元 (`POST /datasets`) で 409 にマップする。

## 既存ルートの path traversal — 本 PR のスコープ

**Hub 関連の新規ルート (`/api/datasets/{ds}/hub*`, `POST /api/datasets/{ds}/hub/push`) のみ `safe_dataset_path()` を使う。**

既存 `datasets.py` の `root / ds` 直結ルート（`DELETE /datasets/{ds}` 等）は同じ穴を持つが、**本 PR では新規ルートにだけ穴を増やさない** ことを最低限の仕様とする。既存ルート全体への適用は別 PR で別タスク化（CLAUDE.md / future work）。

ただし `DELETE /datasets/{ds}` は本 PR で push 調停のために手を入れるので、ついでに `safe_dataset_path()` を入れる（境界条件の最小スコープ）。

## Open questions / future work

- **v2: multi-machine 同時 push** — branch + PR モデル、または専用 lock service
- **v2: 進捗の細かさ** — `upload_large_folder` の internals に手を入れて per-file 進捗を取る、SSE で push
- **v2: README.md (dataset card) 自動生成** — `info.json` から markdown 生成、push に含める
- **v2: cancel API** — push を途中で止める手段
- **v2: pull / sync** — Hub から手元への取得方向

## Risks

| リスク | 対策 |
|---|---|
| `huggingface_hub` の API 仕様変更 | `>=0.34, <1.0` 等の上限を pin、CI で latest_deps テスト |
| HF Hub の rate limit / quota | 失敗時は `last_push_error` に記録、ユーザーが目視で再試行 |
| 同 mount 前提が壊れる（`.pending/` を別 mount に置かれる） | spec で明記、`os.replace` 失敗時のエラーメッセージで案内 |
| hardlink snapshot の cleanup 失敗 | プロセス起動時に `.push-snapshot-*` を全削除、cleanup 失敗もログだけで継続 |
| 巨大 dataset (>50GB) の hash 計算が遅い | `path + size + mtime_ns` のみで hash、内容は読まない（既決） |
| symlink を含む既存 dataset がある | snapshot で fail、ユーザーに symlink 解消を促すエラー |
