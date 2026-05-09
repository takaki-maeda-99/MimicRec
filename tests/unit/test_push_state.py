from __future__ import annotations
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from mimicrec.cloud.push_state import PushCoordinator, PushProgress


def test_progress_default():
    p = PushProgress()
    assert p.status == "idle"
    assert p.error is None


def test_try_reserve_returns_true_first():
    c = PushCoordinator()
    assert c.try_reserve("ds_a") is True
    assert c.try_reserve("ds_a") is False
    c.release("ds_a")
    assert c.try_reserve("ds_a") is True


def test_try_reserve_concurrent_only_one_wins():
    c = PushCoordinator()
    results: list[bool] = []
    barrier = threading.Barrier(20)

    def worker():
        barrier.wait()
        results.append(c.try_reserve("ds_a"))

    with ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(lambda _: worker(), range(20)))

    assert results.count(True) == 1
    assert results.count(False) == 19


def test_get_save_lock_is_rlock():
    c = PushCoordinator()
    lock = c.get_save_lock("ds_a")
    # RLock: same thread can acquire twice
    assert lock.acquire(timeout=1)
    try:
        assert lock.acquire(timeout=1)
        lock.release()
    finally:
        lock.release()


def test_get_save_lock_returns_same_instance():
    c = PushCoordinator()
    a = c.get_save_lock("ds_a")
    b = c.get_save_lock("ds_a")
    assert a is b


def test_drop_dataset_clears_state():
    c = PushCoordinator()
    c.try_reserve("ds_a")
    c.get_save_lock("ds_a")
    c.progress["ds_a"] = PushProgress(status="done")
    c.drop_dataset("ds_a")
    assert "ds_a" not in c.in_flight
    assert "ds_a" not in c.save_locks
    assert "ds_a" not in c.progress


def test_try_reserve_delete_blocks_when_push_in_flight():
    c = PushCoordinator()
    assert c.try_reserve("ds") is True
    assert c.try_reserve_delete("ds") is False
    c.release("ds")
    assert c.try_reserve_delete("ds") is True


def test_try_reserve_delete_blocks_subsequent_push():
    c = PushCoordinator()
    assert c.try_reserve_delete("ds") is True
    # delete reservation prevents push reservation (same in_flight set)
    assert c.try_reserve("ds") is False
