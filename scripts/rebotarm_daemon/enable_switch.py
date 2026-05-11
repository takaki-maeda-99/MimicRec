"""Optional hardware enable-switch (deadman) for the reBotArm daemon.

When configured and active, the switch input puts the daemon into a
"locked" state: the arm holds its current pose in POSITION mode and the
ZMQ server rejects motion commands. Releasing the switch drops the
daemon to GRAVITY_COMP and waits for an explicit set_mode from the
client — it never auto-resumes a previous mode, to avoid surprise
motion.

The backend is libgpiod v2 (python ``gpiod`` 2.x), which works on both
Raspberry Pi 5 and Jetson family. Pin identity is given by
``chip`` + ``line`` (offset or line-name) so the same daemon binary
moves between boards by only editing YAML.

Importing this module does not require ``gpiod`` to be installed —
``make_enable_switch`` lazy-imports it and falls back to a no-op when
gpiod or the chip is unavailable (e.g., running the daemon on a
non-Pi/Jetson machine for testing). This keeps the daemon operational
even without a working switch; absence of the switch simply means the
software path is always "unlocked".
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from rebotarm_daemon.config import EnableSwitchParams


class DebouncedLatch:
    """Pure-python debounce latch — no I/O.

    Fed a stream of raw boolean observations via ``update(raw, now_t)``,
    the latch only flips its publicly-visible ``state`` after ``raw`` has
    persisted at the new value for ``debounce_s`` of monotonic time.
    Chatter (rapid bouncing between True/False) resets the countdown.

    Extracted from ``EnableSwitch`` so the debounce semantics can be
    unit-tested without touching real GPIO — drive ``update`` with
    synthetic timestamps and assert ``state`` transitions.
    """

    def __init__(self, initial: bool, debounce_s: float) -> None:
        self._state = bool(initial)
        self._candidate = bool(initial)
        # Far in the past so an immediate raw==candidate==state observation
        # doesn't accidentally trigger a transition on the first update.
        self._last_change_t = -float("inf")
        self._debounce = max(0.0, float(debounce_s))

    def update(self, raw: bool, now_t: float) -> None:
        raw = bool(raw)
        if raw != self._candidate:
            self._candidate = raw
            self._last_change_t = now_t
        elif (
            raw != self._state
            and (now_t - self._last_change_t) >= self._debounce
        ):
            self._state = raw

    @property
    def state(self) -> bool:
        return self._state


def _resolve_bias(s: str):
    import gpiod
    table = {
        "pull_up": gpiod.line.Bias.PULL_UP,
        "pull_down": gpiod.line.Bias.PULL_DOWN,
        "disabled": gpiod.line.Bias.DISABLED,
        "as_is": gpiod.line.Bias.AS_IS,
    }
    return table[s]


class EnableSwitch:
    """Thread-safe wrapper around a libgpiod input line.

    A background poll thread reads the line at ``poll_hz`` and updates
    an atomic ``_locked`` bool. ``is_locked()`` is callable from any
    thread without locking; bool reads/writes are atomic in CPython.

    The poll thread also debounces transitions: a level change must
    persist for ``debounce_ms`` before it is reflected in ``is_locked()``.
    This kills mechanical chatter from cheap switches without needing
    edge-interrupt support.
    """

    def __init__(self, params: EnableSwitchParams) -> None:
        import gpiod
        from gpiod.line import Direction

        chip_path = (
            params.chip
            if params.chip.startswith("/")
            else f"/dev/{params.chip}"
        )
        self._chip = gpiod.Chip(chip_path)
        # Accept either an integer offset or a string line-name from the
        # board DTB. line_offset_from_id resolves names; integers go
        # through unchanged.
        if isinstance(params.line, str):
            offset = self._chip.line_offset_from_id(params.line)
        else:
            offset = int(params.line)
        self._offset = offset
        self._request = self._chip.request_lines(
            consumer="rebotarm-daemon-enable-switch",
            config={
                offset: gpiod.LineSettings(
                    direction=Direction.INPUT,
                    bias=_resolve_bias(params.bias),
                ),
            },
        )
        self._gpiod = gpiod
        self._active_high = params.active_state == "high"
        self._poll_period = 1.0 / max(1e-3, float(params.poll_hz))
        self._latch = DebouncedLatch(
            initial=self._read_raw(),
            debounce_s=float(params.debounce_ms) / 1000.0,
        )
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop,
            name="rebotarm-enable-switch",
            daemon=True,
        )
        self._thread.start()

    def _read_raw(self) -> bool:
        val = self._request.get_value(self._offset)
        high = val == self._gpiod.line.Value.ACTIVE
        return high if self._active_high else not high

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self._read_raw()
            except Exception:
                # Don't crash the daemon on a transient read error;
                # keep the last known state and retry next tick.
                time.sleep(self._poll_period)
                continue
            self._latch.update(raw, time.monotonic())
            time.sleep(self._poll_period)

    def is_locked(self) -> bool:
        return self._latch.state

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        try:
            self._request.release()
        except Exception:
            pass
        try:
            self._chip.close()
        except Exception:
            pass


def make_enable_switch(
    params: Optional[EnableSwitchParams],
) -> Optional[EnableSwitch]:
    """Return an ``EnableSwitch`` instance, or ``None`` if disabled.

    Returns ``None`` when ``params is None`` (section omitted from YAML)
    or when initialisation fails — gpiod missing, chip not present,
    line offset out of range, etc. A failed init is logged but does not
    raise: the daemon should still come up on dev machines without GPIO.
    """
    if params is None:
        return None
    try:
        return EnableSwitch(params)
    except ImportError as e:
        print(
            f"[rebotarm-daemon] enable_switch configured but gpiod "
            f"unavailable: {e}; switch disabled",
            flush=True,
        )
        return None
    except Exception as e:
        print(
            f"[rebotarm-daemon] enable_switch init failed ({type(e).__name__}: "
            f"{e}); switch disabled",
            flush=True,
        )
        return None
