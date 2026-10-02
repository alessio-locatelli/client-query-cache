from __future__ import annotations

from typing import Any

import pytest

from client_query_cache._core.find_one_reads import find_one_options_cacheable

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "collation",
    [
        pytest.param({}, id="missing-locale-type-error"),
        pytest.param({"locale": 1}, id="non-string-locale-type-error"),
        pytest.param(
            {"locale": "en", "caseLevel": 1}, id="non-boolean-case-level-type-error"
        ),
        pytest.param(
            {"locale": "en", "strength": "high"}, id="non-numeric-strength-value-error"
        ),
    ],
)
def test_collation_rejected_by_pymongo_is_not_cacheable(
    collation: dict[str, Any],
) -> None:
    assert find_one_options_cacheable(None, collation) is False
