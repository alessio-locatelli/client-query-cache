from __future__ import annotations

from typing import Any

import pytest

from client_query_cache._core.find_one_reads import (
    find_one_options_cacheable,
    find_one_read_shape,
)

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


@pytest.mark.parametrize(
    ("left", "right", "equal"),
    [(None, {}, True), (None, {"a": 1}, False), ({"a": 1}, {"a": 1.0}, False)],
    ids=["empty-remainder", "nonempty-remainder", "bson-numeric-types"],
)
def test_find_one_read_shape_retains_remainder(
    left: dict[str, object] | None,
    right: dict[str, object],
    *,
    equal: bool,
) -> None:
    default_shape = find_one_read_shape(None, None, None, "codec")
    left_shape = (
        default_shape
        if left is None
        else find_one_read_shape(None, None, None, "codec", left)
    )
    right_shape = find_one_read_shape(None, None, None, "codec", right)
    assert (left_shape == right_shape) is equal
