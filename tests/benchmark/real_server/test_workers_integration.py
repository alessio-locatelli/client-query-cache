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
    write_documents_until_stopped,
)

if TYPE_CHECKING:
    from collections.abc import Callable

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
    writer = threading.Thread(
        target=write_documents_until_stopped,
        args=(
            mongodb_uri,
            seed_documents,
            document_ids,
            _WRITER_UPDATE_INTERVAL_SECONDS,
            stop_event,
        ),
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


def test_uncached_reader_sends_one_find_command_per_read(
    mongodb_uri: MongoDbUri,
    seed_documents: list[dict[str, Any]],
    document_ids: list[str],
) -> None:
    with MongoClient[dict[str, Any]](mongodb_uri) as client:
        client[DATABASE_NAME][COLLECTION_NAME].insert_many(seed_documents)

    read_result = read_documents_repeatedly(
        mongodb_uri,
        document_ids,
        use_cache=False,
        warmup_cycles=2,
        measured_cycles=3,
    )

    assert read_result.find_command_count == len(document_ids) * 3


def test_cached_reader_excludes_warmup_and_change_stream_polling(
    mongodb_uri: MongoDbUri,
    seed_documents: list[dict[str, Any]],
    document_ids: list[str],
) -> None:
    with MongoClient[dict[str, Any]](mongodb_uri) as client:
        client[DATABASE_NAME][COLLECTION_NAME].insert_many(seed_documents)

    read_result = read_documents_repeatedly(
        mongodb_uri,
        document_ids,
        use_cache=True,
        warmup_cycles=5,
        measured_cycles=3,
    )

    assert read_result.find_command_count == 0
