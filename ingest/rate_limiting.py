import time
from dataclasses import dataclass


@dataclass(frozen=True)
class BucketState:
    tokens: float
    updated_at: float


def refill(state, now, rate_per_second, capacity):
    """Add whatever tokens time has earned since we last looked."""
    elapsed = max(0.0, now - state.updated_at)
    tokens = min(capacity, state.tokens + elapsed * rate_per_second)
    return BucketState(tokens=tokens, updated_at=now)

def seconds_until_available(state, rate_per_second, tokens_needed=1.0):
    """How long until the bucket holds enough. 0.0 if it already does."""
    missing = tokens_needed - state.tokens
    if missing <= 0:
        return 0.0
    return missing / rate_per_second

class TokenBucket:
    def __init__(self, rate_per_second, capacity, now=None):
        if rate_per_second <= 0:
            raise ValueError(f"rate_per_second must be positive, got {rate_per_second}")
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")

        self.rate_per_second = rate_per_second
        self.capacity = capacity
        self._state = BucketState(
            tokens=float(capacity),
            updated_at=time.monotonic() if now is None else now,
        )

    def acquire(self, now=None, sleep=time.sleep):
        """Spend one token, waiting if the bucket is empty. Returns seconds waited."""
        now = time.monotonic() if now is None else now

        state = refill(self._state, now, self.rate_per_second, self.capacity)
        wait = seconds_until_available(state, self.rate_per_second)

        if wait > 0:
            sleep(wait)
            state = refill(state, now + wait, self.rate_per_second, self.capacity)

        self._state = BucketState(tokens=state.tokens - 1.0, updated_at=state.updated_at)
        return wait