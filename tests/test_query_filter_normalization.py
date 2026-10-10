from __future__ import annotations

from collections.abc import Awaitable
from typing import TYPE_CHECKING

import pytest
from pymongo import ReadPreference
from pymongo.collation import Collation
from pymongo.errors import OperationFailure
from pymongo.read_concern import ReadConcern

from client_query_cache._types import BsonDict
from tests.cursor_helpers import materialize
from tests.polling import wait_until_async

if TYPE_CHECKING:
    from pymongo.asynchronous.collection import AsyncCollection
    from pymongo.synchronous.collection import Collection

    from tests.cursor_fixtures import Binding

pytestmark = pytest.mark.integration


@pytest.fixture
async def filter_examples(cursors: Binding) -> Binding:
    view = cursors["view"]
    examples = [
        {
            "_id": 1000,
            "status": "active",
            "region": "eu",
            "metadata": {"a": 1, "b": 2},
            "array": [1, 2],
        },
        {
            "_id": 1001,
            "status": "ACTIVE",
            "region": "eu",
            "metadata": {"b": 2, "a": 1},
            "array": [2, 1],
        },
    ]
    inserted = view.raw.insert_many(examples)
    if isinstance(inserted, Awaitable):
        await inserted

    async def ready() -> bool:
        before = view.database.manager.snapshot().hits
        assert await materialize(view.find({"_id": "filter-ready"})) == []
        return view.database.manager.snapshot().hits > before

    await wait_until_async(ready)
    view.database.manager.cache_core.clear_namespace(view._namespace())
    cursors["commands"].commands.clear()
    return cursors


@pytest.fixture
def native_filters(
    filter_examples: Binding,
) -> Collection[BsonDict] | AsyncCollection[BsonDict]:
    return filter_examples["view"].raw.with_options(
        read_preference=ReadPreference.PRIMARY, read_concern=ReadConcern("majority")
    )


@pytest.mark.parametrize(
    ("filter_document", "collation"),
    [
        ({"payload": "", "nested.original": True}, None),
        ({"payload": "", "value": 1}, None),
        ({"payload": "", "value": 1.0}, None),
        ({"absent": None, "payload": ""}, None),
        ({"status": "active", "region": "eu"}, None),
        ({"status": "absent", "region": "eu"}, None),
        ({"status": "active", "region": "eu"}, Collation("en", strength=2)),
    ],
    ids=["bool", "int", "float", "null-missing", "string", "empty", "collation"],
)
async def test_scalar_permutations_match_native_and_reuse_one_payload(
    filter_examples: Binding,
    native_filters: Collection[BsonDict] | AsyncCollection[BsonDict],
    filter_document: BsonDict,
    collation: Collation | None,
) -> None:
    view = filter_examples["view"]
    expected = await materialize(
        native_filters.find(filter_document, collation=collation).sort("_id")
    )
    filter_examples["commands"].commands.clear()
    assert (
        await materialize(
            view.find(filter_document, None, 0, 0, collation=collation).sort("_id")
        )
        == expected
    )
    cold_find = next(
        command for command in filter_examples["commands"].commands if "find" in command
    )
    assert tuple(cold_find["filter"].items()) == tuple(filter_document.items())
    core = view.database.manager.cache_core
    before = core.snapshot()
    assert before.entry_count == 1
    filter_examples["commands"].commands.clear()
    reversed_filter = dict(reversed(tuple(filter_document.items())))
    assert (
        await materialize(view.find(reversed_filter, collation=collation).sort("_id"))
        == expected
    )
    after = core.snapshot()
    assert after.hits == before.hits + 1
    assert after.entry_count == before.entry_count
    assert after.used_bytes == before.used_bytes
    assert filter_examples["commands"].commands == []


@pytest.mark.parametrize(
    "filter_document",
    [
        {"metadata": {"a": 1, "b": 2}, "region": "eu"},
        {"array": [1, 2], "region": "eu"},
        {"value": {"$eq": 1}, "payload": ""},
    ],
    ids=["document", "array", "operator"],
)
async def test_declined_filters_keep_ordered_identity_and_exact_hits(
    filter_examples: Binding,
    native_filters: Collection[BsonDict] | AsyncCollection[BsonDict],
    filter_document: BsonDict,
) -> None:
    view = filter_examples["view"]
    expected = await materialize(native_filters.find(filter_document).sort("_id"))
    await materialize(view.find(filter_document).sort("_id"))
    core = view.database.manager.cache_core
    before = core.snapshot()
    filter_examples["commands"].commands.clear()
    assert await materialize(view.find(filter_document).sort("_id")) == expected
    assert core.snapshot().hits == before.hits + 1
    assert filter_examples["commands"].commands == []
    reversed_filter = dict(reversed(tuple(filter_document.items())))
    assert await materialize(view.find(reversed_filter).sort("_id")) == expected
    assert (
        sum("find" in command for command in filter_examples["commands"].commands) == 1
    )
    after_reverse = core.snapshot()
    assert after_reverse.entry_count == before.entry_count + 1
    assert after_reverse.hits == before.hits + 1
    assert after_reverse.bypass_reasons == before.bypass_reasons
    filter_examples["commands"].commands.clear()
    assert await materialize(view.find(reversed_filter).sort("_id")) == expected
    assert core.snapshot().hits == after_reverse.hits + 1
    assert filter_examples["commands"].commands == []


@pytest.mark.parametrize(
    ("field", "first", "second"),
    [("metadata", {"a": 1, "b": 2}, {"b": 2, "a": 1}), ("array", [1, 2], [2, 1])],
    ids=["document", "array"],
)
async def test_literal_order_matches_native_with_separate_cache_entries(
    filter_examples: Binding,
    native_filters: Collection[BsonDict] | AsyncCollection[BsonDict],
    *,
    field: str,
    first: object,
    second: object,
) -> None:
    view = filter_examples["view"]
    expected_first = await materialize(native_filters.find({field: first}).sort("_id"))
    expected_second = await materialize(
        native_filters.find({field: second}).sort("_id")
    )
    filter_examples["commands"].commands.clear()
    assert await materialize(view.find({field: first}).sort("_id")) == expected_first
    assert await materialize(view.find({field: second}).sort("_id")) == expected_second
    assert (
        sum("find" in command for command in filter_examples["commands"].commands) == 2
    )
    assert view.database.manager.snapshot().entry_count == 2


async def test_invalid_filter_keeps_native_error_after_warming(
    cursors: Binding,
) -> None:
    view = cursors["view"]
    await materialize(view.find({"payload": "", "nested.original": True}).sort("_id"))
    before = view.database.manager.snapshot()
    invalid_filter = {"payload": {"$invalid": 1}, "nested.original": True}
    with pytest.raises(OperationFailure) as native_error:
        await materialize(view.raw.find(invalid_filter).sort("_id"))
    with pytest.raises(OperationFailure) as cached_error:
        await materialize(view.find(invalid_filter).sort("_id"))
    assert cached_error.value.code == native_error.value.code
    assert view.database.manager.snapshot().hits == before.hits
