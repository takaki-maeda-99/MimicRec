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
