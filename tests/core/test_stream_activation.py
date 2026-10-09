from __future__ import annotations

from unittest.mock import Mock

import pytest

from client_query_cache._core import stream_activation
from client_query_cache._core.stream_activation import StartupRetry
from client_query_cache._types import Probability

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("fraction", [0.5, 1.0], ids=["lower-bound", "upper-bound"])
def test_retry_deadlines_grow_and_saturate(
    monkeypatch: pytest.MonkeyPatch, fraction: Probability
) -> None:
    clock = Mock(return_value=10.0)
    sampler = Mock(side_effect=lambda _low, high: high * fraction)
    monkeypatch.setattr(stream_activation, "monotonic", clock)
    monkeypatch.setattr(
        "client_query_cache._core.stream_activation.random.uniform", sampler
    )
    retry = StartupRetry()
    assert retry.ready()
    for cap in (0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 12.8, 25.6, 30.0, 30.0):
        retry.failed()
        sampler.assert_called_with(cap / 2, cap)
        assert retry.deadline == pytest.approx(10.0 + cap * fraction)
        assert not retry.ready()
        clock.return_value = retry.deadline
        assert retry.ready()
        clock.return_value = 10.0
