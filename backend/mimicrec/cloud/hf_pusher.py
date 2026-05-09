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
