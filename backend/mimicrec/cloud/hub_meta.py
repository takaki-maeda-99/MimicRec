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
    try:
        raw = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    known = {f.name for f in fields(HubMeta)}
    filtered = {k: v for k, v in raw.items() if k in known}
    try:
        return HubMeta(**filtered)
    except (TypeError, ValueError):
        return None


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
