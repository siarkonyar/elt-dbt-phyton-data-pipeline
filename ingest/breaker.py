import time
from dataclasses import dataclass

HEALTHY = "healthy"
TRIPPED = "tripped"
TESTING = "testing"


class CircuitTrippedError(RuntimeError):
    """Raised instead of making a request we already know will fail."""


@dataclass(frozen=True)
class BreakerState:
    status: str
    consecutive_failures: int
    tripped_at: float


def initial_state():
    return BreakerState(status=HEALTHY, consecutive_failures=0, tripped_at=0.0)

def allows_request(state, now, cooldown_seconds):
    if state.status == HEALTHY:
        return True, state

    if state.status == TESTING:
        return True, state

    # Only TRIPPED reaches here: let one request through once the cooldown ends.
    waited = now - state.tripped_at

    if waited >= cooldown_seconds:
        return True, BreakerState(TESTING, state.consecutive_failures, state.tripped_at)

    return False, state


def after_success(state):
    return initial_state()


def after_failure(state, now, failure_threshold):
    failures = state.consecutive_failures + 1

    # A failure while TESTING trips again immediately -- we already know it broke.
    if state.status == TESTING or failures >= failure_threshold:
        return BreakerState(TRIPPED, failures, now)

    return BreakerState(HEALTHY, failures, state.tripped_at)

class CircuitBreaker:
    def __init__(self, failure_threshold, cooldown_seconds):
        if failure_threshold < 1:
            raise ValueError(f"failure_threshold must be at least 1, got {failure_threshold}")
        if cooldown_seconds <= 0:
            raise ValueError(f"cooldown_seconds must be positive, got {cooldown_seconds}")

        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._state = initial_state()

    @property
    def status(self):
        return self._state.status

    def before_request(self, now=None):
        now = time.monotonic() if now is None else now
        allowed, self._state = allows_request(self._state, now, self.cooldown_seconds)

        if not allowed:
            remaining = self.cooldown_seconds - (now - self._state.tripped_at)
            raise CircuitTrippedError(
                f"circuit tripped after {self._state.consecutive_failures} "
                f"failures; retrying in {remaining:.1f}s"
            )

    def record_success(self):
        self._state = after_success(self._state)

    def record_failure(self, now=None):
        now = time.monotonic() if now is None else now
        self._state = after_failure(self._state, now, self.failure_threshold)