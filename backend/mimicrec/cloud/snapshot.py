from __future__ import annotations
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.recording.atomic_io import _atomic_write_parquet, _atomic_write_text


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
    On failure, removes any partial snapshot dir before re-raising."""
    syms = detect_symlinks(ds_root)
    if syms:
        raise SnapshotError(
            f"dataset contains symlinks (forbidden in v1): {syms}"
        )
    snapshot = ds_root.parent / f".push-snapshot-{ds_root.name}-{uuid4().hex[:8]}"

    def _ignore(_dir, names):
        return [n for n in names if n in SNAPSHOT_IGNORE]

    try:
        shutil.copytree(
            ds_root, snapshot,
            copy_function=os.link, ignore=_ignore,
            dirs_exist_ok=False, symlinks=False,
        )
        _strip_tombstoned(snapshot)
        return snapshot
    except BaseException:
        shutil.rmtree(snapshot, ignore_errors=True)
        raise


def _strip_tombstoned(snapshot: Path) -> None:
    """Remove tombstoned episode data/video files in the snapshot, then rewrite
    episodes.parquet and info.json to exclude deleted rows."""
    eps_pq = snapshot / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    if not eps_pq.exists():
        return
    rows = pq.read_table(eps_pq).to_pylist()
    deleted = [r for r in rows if r.get("deleted")]
    if not deleted:
        return

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

    kept = [r for r in rows if not r.get("deleted")]
    offset = 0
    for r in sorted(kept, key=lambda x: x["episode_index"]):
        r["dataset_from_index"] = offset
        r["dataset_to_index"] = offset + r.get("length", 0)
        offset = r["dataset_to_index"]
    if kept:
        _atomic_write_parquet(pa.Table.from_pylist(kept), eps_pq)
    else:
        eps_pq.unlink(missing_ok=True)

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


def recover_interrupted_push(datasets_root: Path) -> list[str]:
    """Called at startup BEFORE cleanup_orphan_snapshots.

    For each `.push-snapshot-<ds>-<hex>` dir found, mark the corresponding
    dataset's hub.json with last_push_error="interrupted ..." so the UI shows
    the prior failure after a SIGKILL/restart.

    Returns list of dataset names that were marked interrupted.
    """
    from mimicrec.cloud.hub_meta import read_hub_meta, write_hub_meta
    if not datasets_root.exists():
        return []
    interrupted: list[str] = []
    for p in datasets_root.iterdir():
        if not p.is_dir() or not p.name.startswith(".push-snapshot-"):
            continue
        rest = p.name[len(".push-snapshot-"):]
        ds_name = rest.rsplit("-", 1)[0]
        ds_root = datasets_root / ds_name
        if not ds_root.exists():
            continue
        meta = read_hub_meta(ds_root)
        if meta is None:
            continue
        meta.last_push_error = "interrupted (process restarted during push)"
        write_hub_meta(ds_root, meta)
        interrupted.append(ds_name)
    return interrupted
