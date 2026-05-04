from __future__ import annotations
from collections import defaultdict


class Metrics:
    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = {}

    def inc(self, name: str, by: int = 1) -> None:
        self._counters[name] += by

    def get(self, name: str) -> int:
        return self._counters[name]

    def set_gauge(self, name: str, value: float) -> None:
        self._gauges[name] = value

    def gauge(self, name: str) -> float:
        return self._gauges.get(name, 0.0)

    def observe(self, name: str, value: float) -> None:
        """Record a sampled value. Currently keeps only the latest (used by /state)."""
        self._gauges[name] = value

    def get_last(self, name: str) -> float | None:
        """Get the most recent observation, or None if never observed."""
        return self._gauges.get(name)

    def snapshot(self) -> dict[str, dict[str, float]]:
        return {"counters": dict(self._counters), "gauges": dict(self._gauges)}
