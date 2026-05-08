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
    sub = tmp_path / "sub"
    sub.mkdir()
    with pytest.raises(UnsafePathError):
        safe_dataset_path(sub, "../sibling")
