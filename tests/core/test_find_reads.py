from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from bson.int64 import Int64

from client_query_cache._core import find_reads as find_module
from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.find_reads import (
    FindReadShape,
    PreparedFindRead,
    find_discriminator,
    find_read_shape,
)
from client_query_cache._core.keys import NamespaceCacheKey
from client_query_cache._types import NonNegativeInt
from tests.call_counting import count_current_thread_calls

if TYPE_CHECKING:
    from faker import Faker

    from client_query_cache._core.keys import NamespaceId
    from client_query_cache._core.manager import CacheCore

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
def test_family_preserves_every_other_final_input(component: NonNegativeInt) -> None:
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
        {"b": 3, "a": 1},
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
        cast("NonNegativeInt", options[3]),
        cast("int", options[4]),
        collation=options[5],
        codec=options[6],
    )
    options[component] = changes[component]
    changed = find_read_shape(
        options[0],
        options[1],
        options[2],
        cast("NonNegativeInt", options[3]),
        cast("int", options[4]),
        collation=options[5],
        codec=options[6],
    )
    assert canonicalize(reference.discriminator) != canonicalize(changed.discriminator)
    assert (canonicalize(reference.family) == canonicalize(changed.family)) is (
        component == 4
    )


@pytest.mark.parametrize("operator", [False, True], ids=["scalar", "operator"])
def test_discriminators_reference_the_canonical_family(
    faker: Faker, *, operator: bool
) -> None:
    value = faker.pyfloat()
    shape = find_read_shape(
        {faker.pystr(): {"$gt": value} if operator else value},
        None,
        {"_id": 1},
        0,
        faker.pyint(min_value=1),
        collation=None,
        codec="codec",
    )
    family = canonicalize(shape.family)
    discriminator = find_discriminator(family, shape.limit)

    assert isinstance(discriminator, tuple)
    assert discriminator[1][0] is family
    assert canonicalize(discriminator) is discriminator
    assert FindReadShape(family, shape.limit).source == shape.source


@pytest.mark.parametrize(
    "filter_document",
    [
        pytest.param({"b": 2, "a": 1}, id="normalized-scalars"),
        pytest.param({"nested": {"b": 2, "a": 1}}, id="ordered-document"),
        pytest.param({"v": 1.0}, id="float"),
        pytest.param({"v": Int64(1)}, id="int64"),
        pytest.param({"v": True}, id="boolean"),
    ],
)
@pytest.mark.parametrize(
    "limit",
    [20, 0, -20, True, False],
    ids=["positive", "unlimited", "negative", "true", "false"],
)
def test_prepared_find_shape_preserves_raw_identity(
    core: CacheCore,
    namespace: NamespaceId,
    monkeypatch: pytest.MonkeyPatch,
    filter_document: object,
    limit: int,
) -> None:
    raw_shape = find_read_shape(
        filter_document,
        {"v": 1},
        {"_id": 1},
        0,
        limit,
        collation=None,
        codec="codec",
    )
    family = canonicalize(raw_shape.family)
    prepared_shape = PreparedFindRead(family, limit)
    exact_key = prepared_shape.discriminator
    raw_key = canonicalize(raw_shape.discriminator)
    assert exact_key == raw_key == canonicalize(prepared_shape.discriminator)
    assert hash(exact_key) == hash(raw_key)
    assert prepared_shape.source == raw_shape.source
    assert isinstance(exact_key, tuple)
    assert exact_key[1][0] is family
    builds = count_current_thread_calls(monkeypatch, find_module, "find_discriminator")
    core.admit_namespace(
        core.capture_namespace_generation(namespace),
        exact_key,
        [],
        find_source=prepared_shape.source,
    )
    assert builds.count == 0
    assert core.lookup_find(namespace, prepared_shape).hit
    assert prepared_shape.discriminator is exact_key
    stored_key = next(iter(core._lru._order))
    assert isinstance(stored_key, NamespaceCacheKey)
    assert stored_key.discriminator is exact_key
    assert builds.count == 0
