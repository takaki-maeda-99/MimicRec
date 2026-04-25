"""Repair a dataset whose episodes.parquet has stale or duplicate entries.

Symptom (from the episode_index reset bug, fixed in commit X): the metadata
file accumulates multiple episode rows with the same `episode_index` because
each session restarted episode numbering from 0. The on-disk parquet/MP4
files only carry the most recent recording for that index — earlier entries
in the metadata point to data that no longer exists.

This script keeps only metadata entries whose data files are still on disk,
and renumbers episode_index sequentially so downstream tools don't choke on
duplicates.

Usage:
    .venv/bin/python scripts/repair_dataset_episodes.py datasets/SO101
    .venv/bin/python scripts/repair_dataset_episodes.py datasets/SO101 --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def _rebuild_info_json(ds: Path, *, dry_run: bool) -> None:
    """Recreate meta/info.json from on-disk data (in case it got deleted)."""
    info_path = ds / "meta" / "info.json"
    if info_path.exists():
        return
    data_dir = ds / "data" / "chunk-000"
    parquets = sorted(data_dir.glob("episode_*.parquet"))
    if not parquets:
        print(f"no parquets in {data_dir}, skipping info.json rebuild")
        return
    sample = pq.read_table(parquets[0])
    cols = sample.column_names

    # Infer fps from timestamp diffs (median).
    import numpy as _np
    fps = 30
    if "timestamp" in cols and sample.num_rows >= 2:
        ts = _np.array([float(r.as_py()) for r in sample.column("timestamp")])
        dt = float(_np.median(_np.diff(ts)))
        if dt > 0:
            fps = int(round(1.0 / dt))

    # Infer joints / cameras from columns.
    dof = 0
    if "action.joint_pos" in cols:
        first = sample.column("action.joint_pos")[0].as_py()
        dof = len(first)
    joint_names = [f"j{i+1}" for i in range(dof)]
    cam_names = sorted({
        c.split(".")[2] for c in cols if c.startswith("observation.images.")
    })

    features = {}
    if dof > 0:
        features["action"] = {"dtype": "float32", "shape": [dof], "names": joint_names}
        features["observation.state"] = {"dtype": "float32", "shape": [dof], "names": joint_names}
    features["timestamp"] = {"dtype": "float32", "shape": [1], "names": None}
    features["frame_index"] = {"dtype": "int64", "shape": [1], "names": None}
    features["episode_index"] = {"dtype": "int64", "shape": [1], "names": None}
    features["index"] = {"dtype": "int64", "shape": [1], "names": None}
    features["task_index"] = {"dtype": "int64", "shape": [1], "names": None}
    for cam in cam_names:
        features[f"observation.images.{cam}"] = {
            "dtype": "video", "shape": [480, 640, 3],
            "names": ["height", "width", "channels"],
            "info": {
                "video.height": 480, "video.width": 640,
                "video.codec": "libx264", "video.pix_fmt": "yuv420p",
                "video.is_depth_map": False, "video.fps": fps,
                "video.channels": 3, "has_audio": False,
            },
        }
    info = {
        "codebase_version": "v3.0",
        "robot_type": "unknown",
        "total_episodes": 0, "total_frames": 0, "total_tasks": 0,
        "chunks_size": 1000,
        "data_files_size_in_mb": 0, "video_files_size_in_mb": 0,
        "fps": fps,
        "splits": {"train": "0:0"},
        "data_path": "data/chunk-{chunk_index:03d}/episode_{episode_index:06d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/episode_{episode_index:06d}.mp4",
        "features": features,
    }
    print(f"  rebuild info.json (fps={fps}, dof={dof}, cameras={cam_names})")
    if not dry_run:
        import json
        info_path.write_text(json.dumps(info, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ds = Path(args.dataset_root)
    _rebuild_info_json(ds, dry_run=args.dry_run)

    meta_pq = ds / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    if not meta_pq.exists():
        print(f"no metadata at {meta_pq}", file=sys.stderr)
        return 1

    rows = pq.read_table(meta_pq).to_pylist()
    data_dir = ds / "data" / "chunk-000"

    # Find the actual row count per on-disk parquet file. We use this to
    # repair the metadata's `length` / `num_frames` fields, which an older
    # bug populated with the session-cumulative writer counter instead of
    # the per-episode count.
    on_disk: dict[int, int] = {}
    for f in data_dir.glob("episode_*.parquet"):
        try:
            idx = int(f.stem.split("_", 1)[1])
        except ValueError:
            continue
        on_disk[idx] = pq.read_table(f).num_rows

    # Keep last metadata row per (episode_index) — most recent wins.
    # In write order, append-only metadata has the most recent row last.
    by_idx: dict[int, dict] = {}
    for r in rows:
        idx = int(r["episode_index"])
        by_idx[idx] = r  # last write wins

    # Drop any whose data files don't exist; repair length to actual row count.
    surviving = []
    for idx, r in sorted(by_idx.items()):
        if idx not in on_disk:
            continue
        actual = on_disk[idx]
        old = r.get("length", r.get("num_frames", -1))
        if old != actual:
            print(f"  ep{idx}: length {old} -> {actual} (corrected)")
            r["length"] = actual
            r["num_frames"] = actual
        surviving.append(r)
    print(f"original rows: {len(rows)}")
    print(f"unique on-disk indices: {len(on_disk)}")
    print(f"surviving metadata rows: {len(surviving)}")

    if args.dry_run:
        print("\n--dry-run, no writes")
        for r in surviving:
            print(f"  idx={r['episode_index']} task={r.get('task')!r} length={r.get('length')}")
        return 0

    # Recompute dataset_from / dataset_to indices contiguously.
    offset = 0
    for r in surviving:
        L = int(r.get("length", r.get("num_frames", 0)))
        r["dataset_from_index"] = offset
        r["dataset_to_index"] = offset + L
        offset += L

    pq.write_table(pa.Table.from_pylist(surviving), meta_pq)
    print(f"\nrewrote {meta_pq} ({len(surviving)} rows)")

    # Refresh info.json totals so /api/datasets returns correct counts.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from mimicrec.recording.metadata import update_info_totals
    update_info_totals(ds / "meta")
    print("info.json totals refreshed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
