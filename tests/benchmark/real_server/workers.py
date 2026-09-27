from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pymongo import MongoClient, ReadPreference
from pymongo.monitoring import CommandListener

from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Sequence
    from multiprocessing import Queue
    from multiprocessing.synchronize import Event as EventClass

    from pymongo.monitoring import CommandStartedEvent, CommandSucceededEvent

DATABASE_NAME = "real_server_benchmark"
COLLECTION_NAME = "documents"

_FIND_COMMAND_NAME = "find"
_CONNECT_TIMEOUT_MS = 5_000
_SERVER_SELECTION_TIMEOUT_MS = 5_000
_SOCKET_TIMEOUT_MS = 5_000


@dataclass(frozen=True, slots=True)
class ReadPhaseResult:
    duration_seconds: float
    find_command_count: int
    max_observed_counter: int


def _bounded_mongo_client(
    uri: str, *, event_listeners: Sequence[CommandListener] = ()
) -> MongoClient[dict[str, Any]]:
    return MongoClient[dict[str, Any]](
        uri,
        connectTimeoutMS=_CONNECT_TIMEOUT_MS,
        serverSelectionTimeoutMS=_SERVER_SELECTION_TIMEOUT_MS,
        socketTimeoutMS=_SOCKET_TIMEOUT_MS,
        event_listeners=event_listeners,
    )


def drop_benchmark_collection(uri: str, collection_name: str) -> None:
    with _bounded_mongo_client(uri) as client:
        client[DATABASE_NAME][collection_name].drop()


def preflight_ping(uri: str) -> None:
    with _bounded_mongo_client(uri) as client:
        client.admin.command("hello", read_preference=ReadPreference.PRIMARY)


def run_preflight_and_start_clock(uri: str) -> float:
    preflight_ping(uri)
    return time.perf_counter()


class _FindCommandCounter(CommandListener):
    def __init__(self) -> None:
        self.find_command_count = 0

    def started(self, event: CommandStartedEvent) -> None:
        if event.command_name == _FIND_COMMAND_NAME:
            self.find_command_count += 1

    def succeeded(self, event: CommandSucceededEvent) -> None:
        pass

    def failed(self, event: Any) -> None:  # noqa: ANN401
        pass


def write_documents_until_stopped(
    uri: str,
    seed_documents: Sequence[dict[str, Any]],
    document_ids: Sequence[str],
    *,
    update_interval_seconds: float,
    stop_event: EventClass,
    collection_name: str,
    ready_event: EventClass,
) -> None:
    drop_benchmark_collection(uri, collection_name)
    with _bounded_mongo_client(uri) as client:
        collection = client[DATABASE_NAME][collection_name]
        collection.insert_many(seed_documents)
        ready_event.set()
        update_index = 0
        while not stop_event.is_set():
            document_id = document_ids[update_index % len(document_ids)]
            collection.update_one(
                {"_id": document_id}, {"$set": {"counter": update_index}}
            )
            update_index += 1
            stop_event.wait(update_interval_seconds)


def _read_each_document(collection: Any, document_ids: Sequence[str]) -> int:  # noqa: ANN401
    max_counter = -1
    for document_id in document_ids:
        document = collection.find_one({"_id": document_id})
        if document is not None:
            max_counter = max(max_counter, document.get("counter", -1))
    return max_counter


def _timed_read_cycles(
    collection: Any,  # noqa: ANN401
    document_ids: Sequence[str],
    warmup_cycles: int,
    measured_cycles: int,
    counter: _FindCommandCounter,
) -> ReadPhaseResult:
    for _ in range(warmup_cycles):
        _read_each_document(collection, document_ids)
    counter.find_command_count = 0
    start = time.perf_counter()
    max_observed_counter = -1
    for _ in range(measured_cycles):
        max_observed_counter = max(
            max_observed_counter, _read_each_document(collection, document_ids)
        )
    duration = time.perf_counter() - start
    return ReadPhaseResult(
        duration_seconds=duration,
        find_command_count=counter.find_command_count,
        max_observed_counter=max_observed_counter,
    )


def read_documents_repeatedly(
    uri: str,
    document_ids: Sequence[str],
    *,
    use_cache: bool,
    warmup_cycles: int,
    measured_cycles: int,
    collection_name: str,
) -> ReadPhaseResult:
    counter = _FindCommandCounter()
    with _bounded_mongo_client(uri, event_listeners=[counter]) as client:
        if use_cache:
            manager = CacheManager(client)
            try:
                cached_collection = manager[DATABASE_NAME][collection_name]
                return _timed_read_cycles(
                    cached_collection,
                    document_ids,
                    warmup_cycles,
                    measured_cycles,
                    counter,
                )
            finally:
                manager.close()
        raw_collection = client[DATABASE_NAME][collection_name]
        return _timed_read_cycles(
            raw_collection, document_ids, warmup_cycles, measured_cycles, counter
        )


def read_documents_repeatedly_into_queue(
    result_queue: Queue[ReadPhaseResult],
    uri: str,
    document_ids: Sequence[str],
    *,
    use_cache: bool,
    warmup_cycles: int,
    measured_cycles: int,
    collection_name: str,
) -> None:
    read_result = read_documents_repeatedly(
        uri,
        document_ids,
        use_cache=use_cache,
        warmup_cycles=warmup_cycles,
        measured_cycles=measured_cycles,
        collection_name=collection_name,
    )
    result_queue.put(read_result)
