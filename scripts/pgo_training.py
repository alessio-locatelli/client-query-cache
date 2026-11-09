from __future__ import annotations

import argparse
import datetime as dt
import os
import random
import string
import time
from contextlib import ExitStack
from contextvars import ContextVar
from typing import TYPE_CHECKING

import bson
from bson import ObjectId
from bson.codec_options import CodecOptions

from client_query_cache import CacheCoreConfig
from client_query_cache import _shared_index as native
from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import codec_fingerprint, encode_value
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.find_one_reads import find_one_read_shape
from client_query_cache._core.find_reads import PreparedFindRead, find_read_shape
from client_query_cache._core.keys import NamespaceId, canonical_alias_key
from client_query_cache._core.order_sensitive_keys import (
    canonical_discriminator_key,
    canonical_order_sensitive_key,
    order_sensitive_key,
)
from client_query_cache._core.query_filters import find_filter_key
from client_query_cache._core.stream_events import route_change_event
from client_query_cache._shared.wire import KeyCache, encode_key

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from typing import Any

    from client_query_cache._core.keys import AliasKey

type Document = dict[str, object]
type Pass = Callable[[], None]
type Workload = tuple[Pass, int]

NAMESPACE = NamespaceId("training", "documents")
SEED = 7
SMALL_BYTES = 200
MEDIUM_BYTES = 2_000
RESIDENT_KEYS = 1024
CHURN_WINDOWS = 64
CAPTURE_DOCUMENTS = 4096
LARGE_IN_ELEMENTS = 256
LIMITED_ENTRIES = 1_000_000
LIMITED_KEY_BYTES = 1_048_576
PRESSURE_ENTRIES = 512
LIMITED_WINDOWS = 24
LIMITED_BUDGET = 2 * 1024 * 1024
BRIEF_SHARE = 0.2
SLOTS = 4096
ARENA_BYTES = 32 * 1024 * 1024
RING_TOKENS = 4096
PROGRESS_EXPIRY_NS = 3_600 * 1_000_000_000
DATABASE = 0
OWNER_LEASE_SECONDS = 30.0
ADMISSION_FRAME_BYTES = 256
ADMISSION_QUEUE_BYTES = 1_048_576
OPTIONS: CodecOptions[Mapping[str, Any]] = CodecOptions()
CLEANUP = ExitStack()
CORE_TELEMETRY_POLICY: ContextVar[bool] = ContextVar(
    "training_telemetry", default=False
)
DEFAULT_DISABLED_SHARE = 0.8


def require(*, condition: bool, reason: str) -> None:
    if not condition:
        raise SystemExit(reason)


def documents(target_bytes: int, count: int) -> list[Document]:
    generator = random.Random(SEED)
    created = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
    generated: list[Document] = []
    for index in range(count):
        document: Document = {
            "_id": ObjectId(generator.randbytes(12)),
            "index": index,
            "name": f"user-{generator.getrandbits(32):08x}",
            "email": f"{generator.getrandbits(32):08x}@example.test",
            "created_at": created + dt.timedelta(seconds=index),
            "padding": "",
        }
        padding = target_bytes - len(bson.encode(document))
        document["padding"] = "".join(
            generator.choices(string.ascii_letters, k=padding)
        )
        generated.append(document)
    return generated


def new_core(budget_bytes: int = 64 * 1024 * 1024) -> native.LocalCacheCore:
    return native.LocalCacheCore(
        CacheCoreConfig(
            budget_bytes=budget_bytes,
            max_entry_bytes=budget_bytes // 4,
            enable_telemetry=CORE_TELEMETRY_POLICY.get(),
        )
    )


def read_shape() -> object:
    return canonicalize(
        find_one_read_shape(None, None, None, codec_fingerprint(OPTIONS))
    )


def verified(
    core: native.LocalCacheCore, run: Pass, *, hits: int = 0, misses: int = 0
) -> None:
    if not core.enable_telemetry:
        run()
        return
    before = core.snapshot()
    run()
    after = core.snapshot()
    recorded = (after.hits - before.hits, after.misses - before.misses)
    require(
        condition=recorded == (hits, misses),
        reason=f"expected {hits} hits and {misses} misses, recorded {recorded}",
    )


def populated_identity_core(
    resident: Sequence[Document],
) -> tuple[native.LocalCacheCore, object]:
    core = new_core()
    shape = read_shape()
    for document in resident:
        capture = core.begin_identity_admission(NAMESPACE, document["_id"])
        core.admit_identity(capture, shape, document, codec_options=OPTIONS)
    return core, shape


def identity_hit(target_bytes: int) -> Workload:
    resident = documents(target_bytes, RESIDENT_KEYS)
    core, shape = populated_identity_core(resident)
    keys = [document["_id"] for document in resident]
    lookup = core.lookup_identity_encoded

    def run() -> None:
        for key in keys:
            lookup(NAMESPACE, key, shape)

    verified(core, run, hits=len(keys))
    return run, len(keys)


def identity_hit_decoded(target_bytes: int) -> Workload:
    resident = documents(target_bytes, RESIDENT_KEYS)
    core, shape = populated_identity_core(resident)
    keys = [document["_id"] for document in resident]
    lookup = core.lookup_identity

    def run() -> None:
        for key in keys:
            lookup(NAMESPACE, key, shape, codec_options=OPTIONS)

    verified(core, run, hits=len(keys))
    return run, len(keys)


def identity_miss() -> Workload:
    core, shape = populated_identity_core(documents(SMALL_BYTES, RESIDENT_KEYS))
    absent = [ObjectId() for _ in range(RESIDENT_KEYS)]
    lookup = core.lookup_identity_encoded

    def run() -> None:
        for key in absent:
            lookup(NAMESPACE, key, shape)

    verified(core, run, misses=len(absent))
    return run, len(absent)


def find_shapes(count: int, limit: int) -> list[PreparedFindRead]:
    return [
        PreparedFindRead(
            canonicalize(
                find_read_shape(
                    {"index": {"$gte": index}},
                    None,
                    {"index": 1},
                    0,
                    limit,
                    collation=None,
                    codec="codec",
                ).family
            ),
            limit,
        )
        for index in range(count)
    ]


def find_hit(*, subsumed: bool) -> Workload:
    payload = encode_value(documents(SMALL_BYTES, 10), OPTIONS)
    stored = find_shapes(256, 10)
    core = new_core()
    for shape in stored:
        capture = core.capture_namespace_generation(NAMESPACE)
        core.admit_namespace_encoded(
            capture, shape.discriminator, payload, find_source=shape.source
        )
    lookups = find_shapes(256, 4) if subsumed else stored
    lookup = core.lookup_find_encoded

    def run() -> None:
        for shape in lookups:
            lookup(NAMESPACE, shape)

    verified(core, run, hits=len(lookups))
    return run, len(lookups)


def namespace_hit() -> Workload:
    payload = encode_value(documents(MEDIUM_BYTES, 16), OPTIONS)
    core = new_core()
    discriminators = [("aggregate", index) for index in range(RESIDENT_KEYS)]
    for discriminator in discriminators:
        capture = core.capture_namespace_generation(NAMESPACE)
        core.admit_namespace_encoded(capture, discriminator, payload)
    lookup = core.lookup_namespace_encoded

    def run() -> None:
        for discriminator in discriminators:
            lookup(NAMESPACE, discriminator)

    verified(core, run, hits=len(discriminators))
    return run, len(discriminators)


def key_windows() -> list[list[int]]:
    return [
        [window * RESIDENT_KEYS + offset for offset in range(RESIDENT_KEYS)]
        for window in range(CHURN_WINDOWS)
    ]


def admit_churn(target_bytes: int) -> Workload:
    document = documents(target_bytes, 1)[0]
    core = new_core(budget_bytes=4 * 1024 * 1024)
    shape = read_shape()
    windows = key_windows()
    begin = core.begin_identity_admission
    admit = core.admit_identity
    position = 0

    def run() -> None:
        nonlocal position
        for key in windows[position]:
            admit(begin(NAMESPACE, key), shape, document, codec_options=OPTIONS)
        position = (position + 1) % CHURN_WINDOWS

    for _ in range(CHURN_WINDOWS):
        run()
    if core.enable_telemetry:
        require(condition=core.snapshot().evictions > 0, reason="churn never evicted")
    return run, RESIDENT_KEYS


def write_invalidation() -> Workload:
    resident = documents(SMALL_BYTES, RESIDENT_KEYS)
    core, shape = populated_identity_core(resident)
    keys = [document["_id"] for document in resident]
    begin = core.begin_identity_admission
    admit = core.admit_identity
    record = core.record_write
    lookup = core.lookup_identity_encoded

    def run() -> None:
        for key, document in zip(keys, resident, strict=True):
            record(NAMESPACE, key)
            admit(begin(NAMESPACE, key), shape, document, codec_options=OPTIONS)

    run()
    require(
        condition=lookup(NAMESPACE, keys[0], shape) is not None,
        reason="write invalidation readmission missed",
    )
    return run, len(keys)


def large_filter() -> dict[str, object]:
    return {
        "status": "active",
        "tenant": {"$in": list(range(LARGE_IN_ELEMENTS))},
        "range": {"$gte": 5, "$lt": 500},
        "tags": ["alpha", "beta", "gamma"],
    }


def key_preparation_large() -> Workload:
    filters = [large_filter() for _ in range(32)]

    def run() -> None:
        for query in filters:
            canonicalize(query)
            find_filter_key(query)
            canonical_discriminator_key(query)

    return run, len(filters)


def key_preparation_small() -> Workload:
    filters = [{"_id": ObjectId()} for _ in range(RESIDENT_KEYS)]
    keys = [query["_id"] for query in filters]

    def run() -> None:
        for query, key in zip(filters, keys, strict=True):
            canonical_order_sensitive_key(key)
            find_filter_key(query)

    return run, len(filters)


def wire_keys() -> Workload:
    keys = [ObjectId() for _ in range(RESIDENT_KEYS)]
    families = [canonicalize(large_filter()) for _ in range(8)]
    cache = KeyCache(64)

    def run() -> None:
        for key in keys:
            encode_key(canonicalize(order_sensitive_key(key)))
        for family in families:
            cache.find(family, 10)
        for index, family in enumerate(families):
            cache.find(family, 100 + index)

    return run, len(keys) + 2 * len(families)


def capture_array() -> Workload:
    envelopes = [
        encode_value(document, OPTIONS)
        for document in documents(SMALL_BYTES, CAPTURE_DOCUMENTS)
    ]

    def run() -> None:
        array = native.EncodedArray(8 * 1024 * 1024)
        append = array.append
        for envelope in envelopes:
            append(envelope)
        array.finish()

    return run, len(envelopes)


def new_owner(index: native.OwnerIndex) -> native.SharedOwnerCore:
    core = native.SharedOwnerCore(
        CacheCoreConfig(
            budget_bytes=4 * 1024 * 1024,
            max_entry_bytes=1024 * 1024,
            enable_telemetry=CORE_TELEMETRY_POLICY.get(),
        ),
        index,
        [NAMESPACE.database],
        16,
        OWNER_LEASE_SECONDS,
    )
    CLEANUP.callback(core.close)
    core.set_database_available(NAMESPACE.database, available=True)
    token = core.begin_namespace_metadata_probe(NAMESPACE)
    require(condition=token is not None, reason="owner namespace was not registered")
    assert token is not None
    require(
        condition=core.namespace_metadata_after_probe(NAMESPACE, token) is not None,
        reason="owner namespace metadata was unavailable",
    )
    return core


def new_index() -> native.OwnerIndex:
    return native.OwnerIndex(
        SLOTS, ARENA_BYTES, 1, 1, random.getrandbits(63), PROGRESS_EXPIRY_NS
    )


def attached_reader(
    index: native.OwnerIndex, ring: native.SessionRing
) -> native.ReaderIndex:
    descriptor = index.reader_descriptor()
    try:
        reader = native.ReaderIndex(descriptor, ring.descriptor())
    finally:
        os.close(descriptor)
    ring.close_descriptor()
    return reader


class SharedIndex:
    __slots__ = (
        "core",
        "epoch",
        "identities",
        "index",
        "keys",
        "payloads",
        "reader",
        "ring",
        "shape",
        "shape_object",
        "slot",
    )

    def __init__(self, target_bytes: int, *, admitted: bool = True) -> None:
        self.shape_object = read_shape()
        self.shape = encode_key(self.shape_object)
        resident = documents(target_bytes, RESIDENT_KEYS)
        self.keys = [document["_id"] for document in resident]
        self.identities = [
            encode_key(canonicalize(order_sensitive_key(key))) for key in self.keys
        ]
        self.payloads = [encode_value(document, OPTIONS) for document in resident]
        self.index = new_index()
        self.core = new_owner(self.index)
        metadata = self.core.registered_namespace_metadata(NAMESPACE)
        require(condition=metadata is not None, reason="owner namespace was absent")
        epoch = self.core.try_current_epoch(NAMESPACE)
        require(condition=epoch is not None, reason="owner namespace had no epoch")
        assert epoch is not None
        self.epoch = epoch
        slot = self.core.assigned_slot(NAMESPACE)
        require(condition=slot is not None, reason="owner assigned no shared slot")
        assert slot is not None
        self.slot = slot
        self.ring = self.index.session_ring(RING_TOKENS)
        self.reader = attached_reader(self.index, self.ring)
        self.index.set_progress(DATABASE, time.monotonic_ns())
        if admitted:
            for key, identity, encoded in zip(
                self.keys, self.identities, self.payloads, strict=True
            ):
                self.admit(key, identity, encoded)

    def admit(self, key: object, identity: bytes, encoded: bytes) -> None:
        outcome = self.core.admit_identity_published(
            self.core.begin_identity_admission(NAMESPACE, key),
            self.shape_object,
            encoded,
            identity,
            self.shape,
        )
        require(
            condition=outcome is AdmissionOutcome.ADMITTED,
            reason=f"shared admission was {outcome}",
        )


def shared_lookup(target_bytes: int, *, hit: bool) -> Workload:
    shared = SharedIndex(target_bytes)
    lookup = shared.reader.lookup
    shape = shared.shape
    absent = encode_key(canonicalize(order_sensitive_key(ObjectId())))
    identities = shared.identities if hit else [absent] * RESIDENT_KEYS
    slot = shared.slot
    epoch = shared.epoch
    require(
        condition=(lookup(*slot, epoch, identities[0], shape) is not None) is hit,
        reason="shared lookup setup disagreed",
    )

    def run() -> None:
        for identity in identities:
            lookup(*slot, epoch, identity, shape)

    return run, len(identities)


def shared_publish_cycle() -> Workload:
    shared = SharedIndex(SMALL_BYTES, admitted=False)
    keys = shared.keys
    identities = shared.identities
    payloads = shared.payloads
    record_write = shared.core.record_write

    def run() -> None:
        for key, identity, encoded in zip(keys, identities, payloads, strict=True):
            shared.admit(key, identity, encoded)
            record_write(NAMESPACE, key)

    run()
    require(condition=shared.index.published() == 0, reason="writes left publications")
    return run, len(identities)


def shared_touch() -> Workload:
    shared = SharedIndex(SMALL_BYTES)
    lookup = shared.reader.lookup
    touch = shared.core.touch
    ring = shared.ring
    identities = shared.identities
    slot = shared.slot
    epoch = shared.epoch
    shape = shared.shape

    def run() -> None:
        for identity in identities:
            lookup(*slot, epoch, identity, shape)
        touch(ring)

    run()
    require(condition=shared.reader.dropped() == 0, reason="touches were dropped")
    return run, len(identities)


def admission_queue() -> Workload:
    index = new_index()
    ring = index.session_ring(RING_TOKENS, ADMISSION_QUEUE_BYTES)
    reader = attached_reader(index, ring)
    generator = random.Random(SEED)
    frames = [generator.randbytes(ADMISSION_FRAME_BYTES) for _ in range(RESIDENT_KEYS)]
    enqueue = reader.enqueue_admission
    drain = ring.drain_admissions

    def run() -> None:
        for frame in frames:
            enqueue(frame)
        drain()

    run()
    for frame in frames:
        require(condition=enqueue(frame), reason="admission queue rejected a frame")
    require(condition=len(drain()) == len(frames), reason="admission queue lost frames")
    return run, len(frames)


def owner_admission() -> Workload:
    payload = encode_value(documents(SMALL_BYTES, 1)[0], OPTIONS)
    shape = read_shape()
    shape_key = encode_key(shape)
    core = new_owner(new_index())
    windows = key_windows()
    identity_keys = {
        key: encode_key(canonicalize(order_sensitive_key(key)))
        for window in windows
        for key in window
    }
    begin = core.begin_identity_admission
    admit = core.admit_identity_published
    position = 0

    def run() -> None:
        nonlocal position
        for key in windows[position]:
            admit(begin(NAMESPACE, key), shape, payload, identity_keys[key], shape_key)
        position = (position + 1) % CHURN_WINDOWS

    for _ in range(CHURN_WINDOWS):
        run()
    require(condition=core.published() > 0, reason="owner never published")
    return run, RESIDENT_KEYS


def facade_hit() -> Workload:
    resident = documents(SMALL_BYTES, RESIDENT_KEYS)
    core, shape = populated_identity_core(resident)
    keys = [document["_id"] for document in resident]
    available = core.is_database_available
    epoch = core.try_current_epoch
    lookup = core.lookup_identity

    def run() -> None:
        for key in keys:
            available(NAMESPACE.database)
            epoch(NAMESPACE)
            canonicalize(key)
            lookup(NAMESPACE, key, shape, codec_options=OPTIONS)

    verified(core, run, hits=len(keys))
    return run, len(keys)


def facade_find_miss() -> Workload:
    payload = encode_value(documents(SMALL_BYTES, 4), OPTIONS)
    core = new_core(budget_bytes=1024 * 1024)
    shapes = find_shapes(RESIDENT_KEYS * 4, 4)
    available = core.is_database_available
    epoch = core.try_current_epoch
    lookup = core.lookup_find
    capture_generation = core.capture_namespace_generation
    admit = core.admit_namespace_encoded
    position = 0

    def run() -> None:
        nonlocal position
        window = shapes[position : position + RESIDENT_KEYS]
        position = (position + RESIDENT_KEYS) % len(shapes)
        for shape in window:
            available(NAMESPACE.database)
            epoch(NAMESPACE)
            lookup(NAMESPACE, shape, codec_options=OPTIONS)
            available(NAMESPACE.database)
            admit(
                capture_generation(NAMESPACE),
                shape.discriminator,
                payload,
                find_source=shape.source,
            )

    for _ in range(4):
        run()
    verified(core, run, misses=RESIDENT_KEYS)
    if core.enable_telemetry:
        require(
            condition=core.snapshot().evictions > 0, reason="find misses never evicted"
        )
    return run, RESIDENT_KEYS


def facade_invalidation() -> Workload:
    resident = documents(SMALL_BYTES, RESIDENT_KEYS)
    core, shape = populated_identity_core(resident)
    keys = [document["_id"] for document in resident]
    wall_time = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
    events = [
        {
            "operationType": "update",
            "ns": {"db": NAMESPACE.database, "coll": NAMESPACE.collection},
            "documentKey": {"_id": key},
            "wallTime": wall_time,
        }
        for key in keys
    ]
    begin = core.begin_identity_admission
    admit = core.admit_identity

    def run() -> None:
        for event, key, document in zip(events, keys, resident, strict=True):
            route_change_event(core, NAMESPACE.database, event)
            admit(begin(NAMESPACE, key), shape, document, codec_options=OPTIONS)

    def invalidations() -> int:
        return core.stream_cost_snapshot(NAMESPACE.database).invalidations

    before = invalidations() if core.enable_telemetry else None
    run()
    if before is not None:
        require(
            condition=invalidations() - before == len(events),
            reason="change events did not invalidate",
        )
    return run, len(events)


def limited_core(max_entries: int) -> native.LocalCacheCore:
    return native.LocalCacheCore(
        CacheCoreConfig(
            budget_bytes=LIMITED_BUDGET,
            max_entry_bytes=LIMITED_BUDGET // 4,
            max_entries=max_entries,
            max_key_bytes=LIMITED_KEY_BYTES,
            enable_telemetry=CORE_TELEMETRY_POLICY.get(),
        )
    )


def rotating(
    items: Sequence[object], run_window: Callable[[Sequence[Any]], None]
) -> Pass:
    position = 0

    def run() -> None:
        nonlocal position
        run_window(items[position : position + RESIDENT_KEYS])
        position = (position + RESIDENT_KEYS) % len(items)

    return run


def limited_namespace_admission(*, entries: int) -> Workload:
    payload = encode_value(documents(MEDIUM_BYTES, 1)[0], OPTIONS)
    core = limited_core(max_entries=entries)
    pipelines = [
        ("aggregate", [{"$match": {"tenant": index % 97}}, {"$limit": index}])
        for index in range(LIMITED_WINDOWS * RESIDENT_KEYS)
    ]
    capture = core.capture_namespace_generation
    admit = core.admit_namespace_encoded

    def run_window(window: Sequence[Any]) -> None:
        for pipeline in window:
            admit(capture(NAMESPACE), pipeline, payload)

    run = rotating(pipelines, run_window)
    for _ in range(LIMITED_WINDOWS):
        run()
    if core.enable_telemetry:
        require(
            condition=core.snapshot().evictions > 0,
            reason="limited churn never evicted",
        )
    return run, RESIDENT_KEYS


def limited_identity_alias_admission() -> Workload:
    document = documents(SMALL_BYTES, 1)[0]
    shape = read_shape()
    core = limited_core(max_entries=PRESSURE_ENTRIES)
    pairs = [
        (
            f"user-{index}",
            canonical_alias_key("email", f"user-{index}@example.test", None),
        )
        for index in range(LIMITED_WINDOWS * RESIDENT_KEYS)
    ]
    begin = core.begin_identity_admission
    admit = core.admit_identity

    def run_window(window: Sequence[Any]) -> None:
        for identity, alias in window:
            admit(
                begin(NAMESPACE, identity),
                shape,
                document,
                alias=alias,
                codec_options=OPTIONS,
            )

    run = rotating(pairs, run_window)
    for _ in range(LIMITED_WINDOWS):
        run()
    if core.enable_telemetry:
        require(
            condition=core.snapshot().entry_count > 0, reason="no value was retained"
        )
    return run, RESIDENT_KEYS


def unique_entries(count: int) -> list[tuple[AliasKey, tuple[AliasKey, object], str]]:
    shape = read_shape()
    entries = []
    for index in range(count):
        alias = canonical_alias_key("handle", f"handle-{index}", None)
        entries.append((alias, (alias, shape), f"account-{index}"))
    return entries


def limited_unique_admission(*, entries: int) -> Workload:
    document = documents(SMALL_BYTES, 1)[0]
    shape = read_shape()
    core = limited_core(max_entries=entries)
    capture = core.capture_namespace_generation
    admit = core.admit_unique_key_match

    def run_window(window: Sequence[Any]) -> None:
        for alias, discriminator, identity in window:
            admit(
                capture(NAMESPACE),
                discriminator,
                identity,
                shape,
                document,
                alias=alias,
            )

    run = rotating(unique_entries(LIMITED_WINDOWS * RESIDENT_KEYS), run_window)
    for _ in range(LIMITED_WINDOWS):
        run()
    if core.enable_telemetry:
        require(
            condition=core.snapshot().entry_count > 0, reason="no value was retained"
        )
    return run, RESIDENT_KEYS


def limited_unique_hit() -> Workload:
    document = documents(SMALL_BYTES, 1)[0]
    shape = read_shape()
    core = limited_core(max_entries=LIMITED_ENTRIES)
    handles = []
    for index, (alias, discriminator, identity) in enumerate(
        unique_entries(RESIDENT_KEYS)
    ):
        core.admit_unique_key_match(
            core.capture_namespace_generation(NAMESPACE),
            discriminator,
            identity,
            shape,
            document,
            alias=alias,
        )
        handles.append((f"handle-{index}", identity))
    available = core.is_database_available
    resolve = core.resolve_alias
    lookup = core.lookup_identity_deferred

    def run() -> None:
        for handle, _identity in handles:
            available(NAMESPACE.database)
            resolved = resolve(NAMESPACE, "handle", handle, None)
            lookup(NAMESPACE, resolved, shape, codec_options=OPTIONS)

    verified(core, run, hits=len(handles))
    return run, len(handles)


WORKLOADS: dict[str, Callable[[], Workload]] = {
    "identity_hit_small": lambda: identity_hit(SMALL_BYTES),
    "identity_hit_medium": lambda: identity_hit(MEDIUM_BYTES),
    "identity_hit_decoded_small": lambda: identity_hit_decoded(SMALL_BYTES),
    "identity_miss": identity_miss,
    "find_exact_hit": lambda: find_hit(subsumed=False),
    "find_subsumed_hit": lambda: find_hit(subsumed=True),
    "namespace_hit": namespace_hit,
    "admit_churn_small": lambda: admit_churn(SMALL_BYTES),
    "admit_churn_medium": lambda: admit_churn(MEDIUM_BYTES),
    "write_invalidation": write_invalidation,
    "key_preparation_large": key_preparation_large,
    "key_preparation_small": key_preparation_small,
    "wire_keys": wire_keys,
    "capture_array": capture_array,
    "shared_hit_small": lambda: shared_lookup(SMALL_BYTES, hit=True),
    "shared_hit_medium": lambda: shared_lookup(MEDIUM_BYTES, hit=True),
    "shared_miss": lambda: shared_lookup(SMALL_BYTES, hit=False),
    "shared_publish_cycle": shared_publish_cycle,
    "shared_touch": shared_touch,
    "admission_queue": admission_queue,
    "owner_admission": owner_admission,
    "facade_hit": facade_hit,
    "facade_find_miss": facade_find_miss,
    "facade_invalidation": facade_invalidation,
    "limited_namespace_roomy": lambda: limited_namespace_admission(
        entries=LIMITED_ENTRIES
    ),
    "limited_namespace_pressure": lambda: limited_namespace_admission(
        entries=PRESSURE_ENTRIES
    ),
    "limited_identity_alias": limited_identity_alias_admission,
    "limited_unique_pair": lambda: limited_unique_admission(entries=PRESSURE_ENTRIES),
    "limited_unique_single": lambda: limited_unique_admission(entries=1),
    "limited_unique_hit": limited_unique_hit,
}


BRIEF = frozenset(
    name
    for name in WORKLOADS
    if name.startswith("limited_") and not name.endswith("_hit")
)


CORE_POLICY_INDEPENDENT = frozenset(
    {
        "key_preparation_large",
        "key_preparation_small",
        "wire_keys",
        "capture_array",
        "shared_hit_small",
        "shared_hit_medium",
        "shared_miss",
        "shared_publish_cycle",
        "shared_touch",
        "admission_queue",
    }
)


def train(
    names: Sequence[str],
    seconds: float,
    *,
    disabled_share: float = DEFAULT_DISABLED_SHARE,
) -> None:
    require(
        condition=0 < disabled_share < 1,
        reason="disabled share must be between zero and one",
    )
    with CLEANUP:
        for name in names:
            modes = (
                ((False, disabled_share), (True, 1 - disabled_share))
                if name not in CORE_POLICY_INDEPENDENT
                else ((False, 1.0),)
            )
            for enabled, weight in modes:
                token = CORE_TELEMETRY_POLICY.set(enabled)
                try:
                    run, _operations = WORKLOADS[name]()
                finally:
                    CORE_TELEMETRY_POLICY.reset(token)
                run()
                share = BRIEF_SHARE if name in BRIEF else 1.0
                deadline = time.monotonic() + seconds * share * weight
                while time.monotonic() < deadline:
                    run()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the native extension's profile-guided optimization training"
    )
    parser.add_argument("--seconds", type=float, default=0.5)
    parser.add_argument("--workloads", nargs="*", default=list(WORKLOADS))
    parser.add_argument("--disabled-share", type=float, default=DEFAULT_DISABLED_SHARE)
    arguments = parser.parse_args()
    train(
        arguments.workloads, arguments.seconds, disabled_share=arguments.disabled_share
    )


if __name__ == "__main__":
    main()
