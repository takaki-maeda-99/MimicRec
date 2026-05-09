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


def test_read_hub_meta_returns_none_on_corrupt_json(tmp_path: Path):
    ds = _mkds(tmp_path)
    hub_meta_path(ds).parent.mkdir(parents=True, exist_ok=True)
    hub_meta_path(ds).write_text("{ this is not valid JSON")
    # 例外を投げず None を返す（未設定扱い）
    assert read_hub_meta(ds) is None


def test_read_hub_meta_returns_none_on_missing_required_field(tmp_path: Path):
    ds = _mkds(tmp_path)
    hub_meta_path(ds).parent.mkdir(parents=True, exist_ok=True)
    # repo_id 必須なのに無い
    hub_meta_path(ds).write_text('{"private": true}')
    assert read_hub_meta(ds) is None
