"""SO101Adapter / SOLeaderAdapter must not let a hardware-side disconnect
exception escape — otherwise ``/session/end`` returns 500 and the operator
cannot exit the session without restarting the backend.

Concrete failure that motivated this: lerobot's ``bus.disconnect()`` calls
``disable_torque(num_retry=5)`` to torque-off the motors before closing the
serial port; when the leader (or follower) is in an alarm state or the cable
has been yanked, the motor returns no status packet and lerobot raises
``ConnectionError("[TxRxResult] There is no status packet!")``. The follower
adapter already wraps disconnect in try/except/finally with a warning log;
the leader adapter did not, so a stuck leader was enough to take down End
Session.

These tests pin the contract:

  * Adapter ``disconnect()`` swallows hardware exceptions raised by the
    underlying lerobot disconnect — they're logged, not propagated.
  * The internal handle is cleared either way, so a subsequent connect
    starts from a clean slate (and a re-call of disconnect is a no-op).
"""
from __future__ import annotations

import pytest


class _ExplodingHardware:
    """Stand-in for lerobot SO101Follower / SOLeader whose disconnect()
    raises — the same shape lerobot exhibits when motors are unresponsive."""

    def __init__(self, exc: Exception):
        self._exc = exc
        self.disconnect_called = False

    def disconnect(self) -> None:
        self.disconnect_called = True
        raise self._exc


@pytest.mark.asyncio
async def test_so101_adapter_disconnect_swallows_lerobot_exception():
    from mimicrec.adapters import so101 as so101_mod

    adapter = so101_mod.SO101Adapter(port="/dev/null", id="x")
    boom = ConnectionError("[TxRxResult] There is no status packet!")
    adapter._follower = _ExplodingHardware(boom)

    # Must not raise.
    await adapter.disconnect()

    assert adapter._follower is None, (
        "adapter must clear the handle even when disconnect failed — "
        "otherwise repeated end calls keep retrying a doomed disconnect"
    )


@pytest.mark.asyncio
async def test_so101_adapter_second_disconnect_is_a_noop():
    """Calling disconnect twice must not raise even if the first call
    encountered an exception. (After the first call's finally clause,
    self._follower is None, so the second call's `if self._follower:`
    short-circuits.)"""
    from mimicrec.adapters import so101 as so101_mod

    adapter = so101_mod.SO101Adapter(port="/dev/null", id="x")
    adapter._follower = _ExplodingHardware(RuntimeError("boom"))

    await adapter.disconnect()
    await adapter.disconnect()  # must be a clean no-op


@pytest.mark.asyncio
async def test_so_leader_adapter_disconnect_swallows_lerobot_exception():
    """Same contract as the follower — the original failure mode that
    surfaced as a 500 on /session/end."""
    from mimicrec.adapters import so_leader as so_leader_mod

    adapter = so_leader_mod.SOLeaderAdapter(port="/dev/null", id="x")
    boom = ConnectionError(
        "Failed to write 'Torque_Enable' on id_=1 with '0' after 6 tries. "
        "[TxRxResult] There is no status packet!"
    )
    adapter._leader = _ExplodingHardware(boom)

    await adapter.disconnect()

    assert adapter._leader is None


@pytest.mark.asyncio
async def test_so_leader_adapter_second_disconnect_is_a_noop():
    from mimicrec.adapters import so_leader as so_leader_mod

    adapter = so_leader_mod.SOLeaderAdapter(port="/dev/null", id="x")
    adapter._leader = _ExplodingHardware(RuntimeError("boom"))

    await adapter.disconnect()
    await adapter.disconnect()
