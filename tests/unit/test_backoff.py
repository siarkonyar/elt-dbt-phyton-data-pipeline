from backoff import ExponentialBackoff


def test_first_delay_falls_within_jitter_range_of_the_minimum():
    backoff = ExponentialBackoff(min_seconds=1, max_seconds=60)

    delay, _ = backoff.next_delay()

    assert 0.5 <= delay <= 1.0


def test_delay_grows_with_each_attempt():
    backoff = ExponentialBackoff(1, 60)

    _, backoff = backoff.next_delay()   # attempts 0 -> 1
    _, backoff = backoff.next_delay()   # attempts 1 -> 2
    delay, _ = backoff.next_delay()     # capped = 1 * 2**2 = 4

    assert 2.0 <= delay <= 4.0


def test_delay_never_exceeds_max_seconds():
    backoff = ExponentialBackoff(1, 5, attempts=20)

    delay, _ = backoff.next_delay()

    assert delay <= 5.0


def test_next_delay_returns_a_backoff_with_one_more_attempt():
    _, advanced = ExponentialBackoff(1, 60).next_delay()

    assert advanced.attempts == 1


def test_next_delay_does_not_mutate_the_original():
    backoff = ExponentialBackoff(1, 60)

    backoff.next_delay()

    assert backoff.attempts == 0


def test_reset_returns_a_backoff_with_no_attempts():
    assert ExponentialBackoff(1, 60, attempts=9).reset().attempts == 0


def test_reset_does_not_mutate_the_original():
    backoff = ExponentialBackoff(1, 60, attempts=9)

    backoff.reset()

    assert backoff.attempts == 9