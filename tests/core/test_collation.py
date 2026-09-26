from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from client_query_cache._core.collation import normalize_collation

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "collation",
    [
        pytest.param(None, id="already-none"),
        pytest.param({"locale": "simple"}, id="simple-locale-only"),
        pytest.param(
            {"locale": "simple", "strength": 3, "caseLevel": False},
            id="simple-locale-with-server-normalized-fields",
        ),
    ],
)
def test_normalize_collation_collapses_simple_collation_to_none(
    collation: Mapping[str, Any] | None,
) -> None:
    assert normalize_collation(collation) is None


def test_normalize_collation_leaves_a_non_simple_collation_untouched() -> None:
    collation = {"locale": "en", "strength": 2}

    assert normalize_collation(collation) == collation
