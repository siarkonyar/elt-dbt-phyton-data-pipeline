import random
from dataclasses import dataclass, replace

MAX_EXPONENT = 32

@dataclass(frozen=True)
class ExponentialBackoff:
    """How long to wait before the next reconnect attempt."""

    min_seconds: float
    max_seconds: float
    attempts: int = 0

    def next_delay(self):
        """Returns (seconds to wait, the backoff to use next time)."""
        exponent = min(self.attempts, MAX_EXPONENT)
        capped = min(self.min_seconds * (2 ** exponent), self.max_seconds)
        jittered = random.uniform(capped / 2, capped)
        return jittered, replace(self, attempts=self.attempts + 1)

    def reset(self):
        """Call after a successful connect so the next failure starts small again."""
        return replace(self, attempts=0)