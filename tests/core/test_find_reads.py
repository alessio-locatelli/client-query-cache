from __future__ import annotations

from typing import cast

import pytest

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.find_reads import find_read_shape

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "limit",
    [0, 10, 100, -10, True, False],
    ids=["unlimited", "small", "large", "negative", "true", "false"],
)
def test_limits_keep_exact_identity_and_share_only_a_family(limit: int) -> None:
    reference = find_read_shape(
        {}, None, {"_id": 1}, 0, 1, collation=None, codec="codec"
    )
    shape = find_read_shape(
        {}, None, {"_id": 1}, 0, limit, collation=None, codec="codec"
    )
    assert canonicalize(reference.discriminator) != canonicalize(shape.discriminator)
    assert canonicalize(reference.family) == canonicalize(shape.family)
    assert (shape.source is not None) is (not isinstance(limit, bool) and limit >= 0)


@pytest.mark.parametrize(
    "component",
    range(7),
    ids=["filter", "projection", "sort", "skip", "limit", "collation", "codec"],
)
def test_family_preserves_every_other_final_input(component: int) -> None:
    options = [
        {"a": 1, "b": 2},
        {"a": 1},
        {"a": 1, "b": -1},
        0,
        100,
        {"locale": "en"},
        "codec",
    ]
    changes = [
        {"b": 2, "a": 1},
        {"b": 1},
        {"b": -1, "a": 1},
        1,
        10,
        {"locale": "fr"},
        "other-codec",
    ]
    reference = find_read_shape(
        options[0],
        options[1],
        options[2],
        cast("int", options[3]),
        cast("int", options[4]),
        collation=options[5],
        codec=options[6],
    )
    options[component] = changes[component]
    changed = find_read_shape(
        options[0],
        options[1],
        options[2],
        cast("int", options[3]),
        cast("int", options[4]),
        collation=options[5],
        codec=options[6],
    )
    assert canonicalize(reference.discriminator) != canonicalize(changed.discriminator)
    assert (canonicalize(reference.family) == canonicalize(changed.family)) is (
        component == 4
    )
