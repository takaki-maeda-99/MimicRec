from __future__ import annotations
import random
from dataclasses import dataclass, field


@dataclass
class FaultProfile:
    latency_ms: float = 0.0
    jitter_ms: float = 0.0
    drop_prob: float = 0.0
    stuck_for_n_calls: int = 0
    rng: random.Random = field(default_factory=random.Random)

    def roll_drop(self) -> bool:
        return self.rng.random() < self.drop_prob

    def sample_delay_s(self) -> float:
        j = self.rng.uniform(-self.jitter_ms, self.jitter_ms)
        return max(0.0, (self.latency_ms + j) / 1000.0)
