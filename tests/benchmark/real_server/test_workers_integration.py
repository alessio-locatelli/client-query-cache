from __future__ import annotations

import multiprocessing
import threading
from typing import TYPE_CHECKING, Any

import pytest
from pymongo import MongoClient

from tests.benchmark.real_server.workers import (
    COLLECTION_NAME,
    DATABASE_NAME,
    read_documents_repeatedly,
    read_documents_repeatedly_into_queue,
    write_documents_until_stopped,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from faker import Faker

    from tests.conftest import MongoDbUri

pytestmark = pytest.mark.integration

_WRITER_UPDATE_INTERVAL_SECONDS = 0.01


@pytest.fixture
def seed_documents(
    make_fake_document: Callable[..., dict[str, Any]],
) -> list[dict[str, Any]]:
    return [make_fake_document() for _ in range(3)]


@pytest.fixture
def document_ids(seed_documents: list[dict[str, Any]]) -> list[str]:
    return [document["_id"] for document in seed_documents]


def test_writer_seeds_and_repeatedly_updates_documents(
    mongodb_uri: MongoDbUri,
    seed_documents: list[dict[str, Any]],
    document_ids: list[str],
) -> None:
    stop_event = multiprocessing.Event()
    ready_event = multiprocessing.Event()
    writer = threading.Thread(
        target=write_documents_until_stopped,
        args=(mongodb_uri, seed_documents, document_ids),
        kwargs={
            "update_interval_seconds": _WRITER_UPDATE_INTERVAL_SECONDS,
            "stop_event": stop_event,
            "collection_name": COLLECTION_NAME,
            "ready_event": ready_event,
        },
    )
    writer.start()
    try:
        with MongoClient[dict[str, Any]](mongodb_uri) as client:
            collection = client[DATABASE_NAME][COLLECTION_NAME]

            def _has_been_updated() -> bool:
                document = collection.find_one({"_id": document_ids[0]})
                return document is not None and document.get("counter", -1) >= 0

            assert any(_has_been_updated() or stop_event.wait(0.05) for _ in range(100))
    finally:
        stop_event.set()
        writer.join()


_MEASURED_CYCLES = 3


@pytest.mark.parametrize(
    ("use_cache", "warmup_cycles"),
    [
        pytest.param(False, 2, id="uncached_sends_one_find_per_read"),
        pytest.param(True, 5, id="cached_excludes_warmup_and_change_stream_polling"),
    ],
)
def test_reader_find_command_count(
    mongodb_uri: MongoDbUri,
    seed_documents: list[dict[str, Any]],
    document_ids: list[str],
    use_cache: bool,
    warmup_cycles: int,
) -> None:
    with MongoClient[dict[str, Any]](mongodb_uri) as client:
        client[DATABASE_NAME][COLLECTION_NAME].insert_many(seed_documents)

    read_result = read_documents_repeatedly(
        mongodb_uri,
        document_ids,
        use_cache=use_cache,
        warmup_cycles=warmup_cycles,
        measured_cycles=_MEASURED_CYCLES,
        collection_name=COLLECTION_NAME,
    )

    expected_find_command_count = (
        0 if use_cache else len(document_ids) * _MEASURED_CYCLES
    )
    assert read_result.find_command_count == expected_find_command_count


def test_reader_tracks_the_max_observed_counter_and_handles_missing_documents(
    mongodb_uri: MongoDbUri,
    seed_documents: list[dict[str, Any]],
    document_ids: list[str],
    faker: Faker,
) -> None:
    updated_counter = 7
    with MongoClient[dict[str, Any]](mongodb_uri) as client:
        collection = client[DATABASE_NAME][COLLECTION_NAME]
        collection.insert_many(seed_documents)
        collection.update_one(
            {"_id": document_ids[0]}, {"$set": {"counter": updated_counter}}
        )

    missing_id = faker.uuid4()
    read_result = read_documents_repeatedly(
        mongodb_uri,
        [*document_ids, missing_id],
        use_cache=False,
        warmup_cycles=0,
        measured_cycles=1,
        collection_name=COLLECTION_NAME,
    )

    assert read_result.max_observed_counter == updated_counter


def test_read_documents_repeatedly_into_queue_puts_the_result(
    mongodb_uri: MongoDbUri,
    seed_documents: list[dict[str, Any]],
    document_ids: list[str],
) -> None:
    with MongoClient[dict[str, Any]](mongodb_uri) as client:
        client[DATABASE_NAME][COLLECTION_NAME].insert_many(seed_documents)

    result_queue: multiprocessing.Queue[Any] = multiprocessing.Queue()
    read_documents_repeatedly_into_queue(
        result_queue,
        mongodb_uri,
        document_ids,
        use_cache=False,
        warmup_cycles=1,
        measured_cycles=_MEASURED_CYCLES,
        collection_name=COLLECTION_NAME,
    )

    read_result = result_queue.get(timeout=5)
    assert read_result.find_command_count == len(document_ids) * _MEASURED_CYCLES
