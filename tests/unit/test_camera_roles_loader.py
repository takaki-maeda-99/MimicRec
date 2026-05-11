import re
import pytest

from mimicrec.api.deps import _load_camera_roles, _SLOT_NAME_RE


def test_loader_returns_roles_list(tmp_path):
    (tmp_path / "camera_roles.yaml").write_text(
        "roles:\n  - front\n  - wrist\n"
    )
    assert _load_camera_roles(tmp_path) == ["front", "wrist"]


def test_loader_missing_file_returns_empty(tmp_path):
    assert _load_camera_roles(tmp_path) == []


def test_slot_name_regex_accepts_valid_names():
    for name in ("front", "wrist", "wrist_2", "top-1", "FRONT", "g_1-2"):
        assert _SLOT_NAME_RE.match(name), f"{name!r} should match"


def test_slot_name_regex_rejects_path_unsafe():
    for name in ("foo/bar", "foo.bar", "", "front bar", "front/", "front."):
        assert not _SLOT_NAME_RE.match(name), f"{name!r} should not match"
