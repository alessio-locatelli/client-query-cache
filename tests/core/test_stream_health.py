from __future__ import annotations

import pytest

from mongo_client_cache._core.stream_health import RetryBackoff

pytestmark = pytest.mark.unit


def test_delay_is_capped_and_grows_with_each_attempt() -> None:
    backoff = RetryBackoff(base_seconds=1.0, max_seconds=4.0, multiplier=2.0)

    caps = [
        backoff.next_delay(random_uniform=lambda _low, high: high) for _ in range(4)
    ]

    assert caps == [1.0, 2.0, 4.0, 4.0]


def test_reset_returns_to_the_base_delay() -> None:
    backoff = RetryBackoff(base_seconds=1.0, max_seconds=4.0, multiplier=2.0)
    backoff.next_delay(random_uniform=lambda _low, high: high)
    backoff.next_delay(random_uniform=lambda _low, high: high)

    backoff.reset()

    assert backoff.next_delay(random_uniform=lambda _low, high: high) == 1.0


def test_delay_is_drawn_from_a_uniform_range_starting_at_zero() -> None:
    backoff = RetryBackoff(base_seconds=1.0, max_seconds=4.0, multiplier=2.0)
    seen_bounds: list[tuple[float, float]] = []

    def record_uniform(low: float, high: float) -> float:
        seen_bounds.append((low, high))
        return low

    backoff.next_delay(random_uniform=record_uniform)

    assert seen_bounds == [(0.0, 1.0)]
