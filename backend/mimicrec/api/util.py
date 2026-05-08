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
