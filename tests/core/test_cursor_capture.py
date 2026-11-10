from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict
from uuid import UUID

import bson
import pytest
from bson.binary import UuidRepresentation
from bson.codec_options import CodecOptions, TypeRegistry
from bson.decimal128 import Decimal128
from bson.raw_bson import RawBSONDocument
from bson.son import SON
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from client_query_cache import CacheCore, CacheCoreConfig, SelectiveInvalidation
from client_query_cache._core.codec import decode_value, encode_value
from client_query_cache._core.cursor_capture import CursorCapture
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.selective_invalidation import (
    normalize_invalidation,
    partition_scalar,
)
from client_query_cache._types import BsonDict, NonNegativeInt, PositiveInt
from tests.codec_helpers import (
    Decimal128ToDecimalDecoder,
    decode_only_decimal_options,
    fail_decimal_encoding,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from decimal import Decimal

    from client_query_cache._core.contracts import LocalCacheCore
    from client_query_cache._core.keys import NamespaceId

pytestmark = pytest.mark.unit
QUERY = ("find", "capture")


class SelectiveCandidate(TypedDict):
    core: LocalCacheCore
    collector: CursorCapture
    namespace: NamespaceId


@pytest.fixture
def selective_candidate(namespace: NamespaceId) -> Iterator[SelectiveCandidate]:
    core = CacheCore(
        CacheCoreConfig(max_entry_bytes=64),
        invalidation=normalize_invalidation(
            {
                (namespace.database, namespace.collection): SelectiveInvalidation(
                    insert_partition_field="author_id"
                )
            }
        ),
    )
    reservations = [
        core.capture_namespace_generation(namespace, partition=partition_scalar(index))
        for index in range(100, 1123)
    ]
    collector = CursorCapture(
        core,
        core.capture_namespace_generation(namespace, partition=partition_scalar(42)),
        QUERY,
        CodecOptions(),
        release_capture=True,
    )
    yield {"core": core, "collector": collector, "namespace": namespace}
    core.close()
    for reservation in reservations:
        reservation.release()


def encode_decimal(value: Decimal) -> Decimal128:
    return Decimal128(str(value))


@pytest.fixture
def core_factory() -> type[LocalCacheCore]:
    return CacheCore


@pytest.fixture(params=[False], ids=["default"])
def core(
    core_factory: type[LocalCacheCore], request: pytest.FixtureRequest
) -> Iterator[LocalCacheCore]:
    core = core_factory(CacheCoreConfig(enable_telemetry=request.param))
    yield core
    core.close()


def test_empty_capture_is_admitted(
    core: LocalCacheCore, namespace: NamespaceId
) -> None:
    capture = capture_for(core, namespace)
    assert capture.finish() is AdmissionOutcome.ADMITTED
    lookup = core.lookup_namespace(namespace, QUERY)
    assert lookup.hit
    assert lookup.value == []


@pytest.fixture
def make_core(
    core_factory: type[LocalCacheCore],
) -> Iterator[Callable[[PositiveInt], LocalCacheCore]]:
    cores: list[LocalCacheCore] = []

    def create(limit: PositiveInt) -> LocalCacheCore:
        core = core_factory(
            CacheCoreConfig(
                budget_bytes=limit * 2, max_entry_bytes=limit, enable_telemetry=True
            )
        )
        cores.append(core)
        return core

    yield create
    for core in cores:
        core.close()


def capture_for(
    core: LocalCacheCore,
    namespace: NamespaceId,
    options: CodecOptions[Mapping[str, Any]] | None = None,
) -> CursorCapture:
    return CursorCapture(
        core,
        core.capture_namespace_generation(namespace),
        QUERY,
        options or CodecOptions(),
    )


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    st.lists(
        st.dictionaries(
            st.text(alphabet="abcdef", min_size=1, max_size=6),
            st.integers(-(2**63), 2**63 - 1),
        ),
        max_size=20,
    )
)
def test_capture_owns_values_before_caller_mutation(
    core: LocalCacheCore, namespace: NamespaceId, documents: list[dict[str, int]]
) -> None:
    core.clear_namespace(namespace)
    expected = [dict(document) for document in documents]
    capture = capture_for(core, namespace)
    for document in documents:
        capture.append(document)
        document.clear()
    assert capture.finish() is AdmissionOutcome.ADMITTED
    assert core.lookup_namespace(namespace, QUERY).value == expected
    assert capture.retained_bytes == 0
    assert capture.finish() is None


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        pytest.param(-1, None, id="over-budget"),
        pytest.param(0, AdmissionOutcome.DECLINED_OVERSIZE, id="exact-budget"),
        pytest.param(1, AdmissionOutcome.DECLINED_OVERSIZE, id="under-budget"),
    ],
)
def test_capture_limit_bounds_retained_document_bytes(
    make_core: Callable[[PositiveInt], LocalCacheCore],
    namespace: NamespaceId,
    delta: int,
    expected: AdmissionOutcome | None,
) -> None:
    document = {"value": "bounded"}
    limit = len(bson.encode(document)) + delta
    core = make_core(limit)
    capture = capture_for(core, namespace)
    capture.append(document)
    assert capture.retained_bytes <= limit
    assert capture.finish() is expected
    assert core.snapshot().oversized_bypasses == 1
    assert capture.retained_bytes == 0


@pytest.mark.parametrize(
    "document", [{"bad": object()}, {"bad": 2**64}], ids=["unencodable", "overflow"]
)
def test_encoding_rejection_discards_previous_snapshots(
    core: LocalCacheCore, namespace: NamespaceId, document: Mapping[str, Any]
) -> None:
    capture = capture_for(core, namespace)
    capture.append({"valid": True})
    capture.append(document)
    capture.append({"also_valid": True})
    assert capture.retained_bytes == 0
    assert capture.finish() is None
    assert not core.lookup_namespace(namespace, QUERY).hit


def test_custom_encoder_failure_discards_native_decoded_candidate(
    core: LocalCacheCore, namespace: NamespaceId
) -> None:
    options: CodecOptions[Mapping[str, Any]] = CodecOptions(
        type_registry=TypeRegistry(
            [Decimal128ToDecimalDecoder()], fallback_encoder=fail_decimal_encoding
        )
    )
    document = bson.decode(
        bson.encode({"price": Decimal128("1.25")}), codec_options=options
    )
    capture = capture_for(core, namespace, options)
    capture.append({"valid": True})
    with pytest.raises(ValueError, match="custom encoding failed"):
        encode_value(document, options)
    capture.append(document)
    capture.append({"also_valid": True})
    assert capture.retained_bytes == 0
    assert capture.finish() is None
    assert not core.lookup_namespace(namespace, QUERY).hit


def test_abandon_releases_snapshots(
    core: LocalCacheCore, namespace: NamespaceId
) -> None:
    capture = capture_for(core, namespace)
    capture.append({"value": True})
    assert capture.retained_bytes > 0
    capture.abandon()
    assert capture.retained_bytes == 0
    assert capture.finish() is None
    assert not core.lookup_namespace(namespace, QUERY).hit


@pytest.mark.parametrize(
    "completion", ["abandon", "oversize", "encoding-failure", "complete"]
)
def test_selective_candidate_releases_its_last_slot_on_every_completion_path(
    selective_candidate: SelectiveCandidate,
    completion: str,
) -> None:
    collector = selective_candidate["collector"]
    core = selective_candidate["core"]
    namespace = selective_candidate["namespace"]
    collector.append({"value": True})
    if completion == "abandon":
        collector.abandon()
    elif completion == "oversize":
        collector.append({"payload": "x" * 1000})
    elif completion == "encoding-failure":
        collector.append({"unencodable": object()})
    else:
        assert collector.finish() is AdmissionOutcome.ADMITTED
        core.clear_namespace(namespace)
    assert collector.finish() is None
    assert collector.retained_bytes == 0
    replacement = core.capture_namespace_generation(
        namespace, partition=partition_scalar(10000)
    )
    core.record_write(namespace, 1, partition=partition_scalar(10001))
    assert (
        core.admit_namespace(replacement, "after-release", 1)
        is AdmissionOutcome.ADMITTED
    )


def make_unavailable(core: LocalCacheCore, namespace: NamespaceId) -> None:
    core.set_database_available(namespace.database, available=False)


def make_unavailable_then_restore(core: LocalCacheCore, namespace: NamespaceId) -> None:
    make_unavailable(core, namespace)
    core.set_database_available(namespace.database, available=True)


@pytest.mark.parametrize(
    ("transition", "expected"),
    [
        pytest.param(
            lambda core, namespace: core.record_write(namespace, "document"),
            AdmissionOutcome.DECLINED_STALE,
            id="write",
        ),
        pytest.param(
            make_unavailable, AdmissionOutcome.DECLINED_UNAVAILABLE, id="unavailable"
        ),
        pytest.param(
            make_unavailable_then_restore,
            AdmissionOutcome.DECLINED_UNAVAILABLE,
            id="restored",
        ),
        pytest.param(lambda core, _namespace: core.close(), None, id="closed-manager"),
    ],
)
@pytest.mark.parametrize("core", [True], indirect=True, ids=["telemetry"])
def test_capture_keeps_existing_admission_guards(
    core: LocalCacheCore,
    namespace: NamespaceId,
    transition: Callable[[LocalCacheCore, NamespaceId], object],
    expected: AdmissionOutcome | None,
) -> None:
    capture = capture_for(core, namespace)
    capture.append({"value": True})
    transition(core, namespace)
    assert capture.finish() is expected
    assert capture.retained_bytes == 0
    assert core.snapshot().entry_count == 0


@pytest.mark.parametrize(
    "options",
    [
        CodecOptions(),
        CodecOptions(document_class=SON),
        CodecOptions(document_class=RawBSONDocument),
        decode_only_decimal_options(),
        CodecOptions(
            type_registry=TypeRegistry(
                [Decimal128ToDecimalDecoder()], fallback_encoder=encode_decimal
            )
        ),
        CodecOptions(uuid_representation=UuidRepresentation.STANDARD),
    ],
    ids=["dict", "ordered", "raw", "custom-decoder", "custom-encoder", "uuid"],
)
def test_finalization_matches_ordinary_cache_codec_round_trip(
    core: LocalCacheCore,
    namespace: NamespaceId,
    options: CodecOptions[Mapping[str, Any]],
) -> None:
    document: BsonDict = {
        "z": Decimal128("1.25"),
        "a": {"second": 2, "first": 1},
        "_id": 2,
    }
    if options.uuid_representation == UuidRepresentation.STANDARD:
        document["uuid"] = UUID("12345678-1234-5678-1234-567812345678")
    decoded = bson.decode(encode_value(document, options), codec_options=options)["v"]
    assert tuple(decoded) == tuple(document)
    expected = decode_value(encode_value([decoded], options), options)
    capture = capture_for(core, namespace, options)
    capture.append(decoded)
    assert capture.finish() is AdmissionOutcome.ADMITTED
    actual = core.lookup_namespace(namespace, QUERY, codec_options=options).value
    assert tuple(actual[0]) == tuple(document)
    # Raw documents are compared by encoded bytes; other classes retain field order.
    assert encode_value(actual, options) == encode_value(expected, options)


def test_exact_final_entry_size_is_enforced(
    make_core: Callable[[PositiveInt], LocalCacheCore], namespace: NamespaceId
) -> None:
    # Final admission also accounts for the list envelope and array element keys.
    documents = [{"value": True}]
    retained = sum(len(bson.encode(document)) for document in documents)
    assert len(encode_value(documents)) > retained
    core = make_core(retained)
    capture = capture_for(core, namespace)
    for document in documents:
        capture.append(document)
    assert capture.retained_bytes == retained
    assert capture.finish() is AdmissionOutcome.DECLINED_OVERSIZE
    assert core.snapshot().oversized_bypasses == 1


def test_snapshots_encode_each_document_once(
    core: LocalCacheCore, namespace: NamespaceId, monkeypatch: pytest.MonkeyPatch
) -> None:
    encoded_documents: list[object] = []
    original_encode = encode_value

    def record(
        document: Mapping[str, Any], options: CodecOptions[Mapping[str, Any]]
    ) -> bytes:
        encoded_documents.append(document)
        return original_encode(document, options)

    monkeypatch.setattr("client_query_cache._core.cursor_capture.encode_value", record)
    documents = [{"n": n} for n in range(10)]
    capture = capture_for(core, namespace)
    for document in documents:
        capture.append(document)
    assert capture.finish() is AdmissionOutcome.ADMITTED
    assert encoded_documents == documents


@pytest.mark.parametrize(
    "count",
    [0, 1, 10, 11, 100, 101],
    ids=["empty", "one", "one-digit-limit", "two-digit", "two-digit-limit", "three"],
)
def test_capture_bytes_match_driver_array_encoding(
    core: LocalCacheCore, namespace: NamespaceId, count: NonNegativeInt
) -> None:
    documents = [{"z": index, "_id": index} for index in range(count)]
    capture = capture_for(core, namespace)
    for document in documents:
        capture.append(document)
    assert capture.finish() is AdmissionOutcome.ADMITTED
    encoded = core.lookup_namespace_encoded(namespace, QUERY)
    assert encoded == encode_value(documents)
    assert isinstance(encoded, bytes)
    assert [tuple(document) for document in decode_value(encoded)] == [  # type: ignore[attr-defined]
        ("z", "_id")
    ] * count


@pytest.mark.parametrize(
    "options",
    [
        CodecOptions(document_class=SON),
        CodecOptions(document_class=RawBSONDocument),
        CodecOptions(
            type_registry=TypeRegistry(
                [Decimal128ToDecimalDecoder()], fallback_encoder=encode_decimal
            )
        ),
    ],
    ids=["ordered", "raw", "custom-encoder"],
)
def test_capture_bytes_match_codec_aware_driver_encoding(
    core: LocalCacheCore,
    namespace: NamespaceId,
    options: CodecOptions[Mapping[str, Any]],
) -> None:
    source = [{"z": Decimal128("1.25"), "_id": index} for index in range(3)]
    documents = [
        bson.decode(encode_value(document, options), codec_options=options)["v"]
        for document in source
    ]
    capture = capture_for(core, namespace, options)
    for document in documents:
        capture.append(document)
    assert capture.finish() is AdmissionOutcome.ADMITTED
    assert core.lookup_namespace_encoded(namespace, QUERY) == encode_value(
        documents, options
    )


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        pytest.param(-1, AdmissionOutcome.DECLINED_OVERSIZE, id="one-byte-short"),
        pytest.param(0, AdmissionOutcome.ADMITTED, id="exact"),
    ],
)
def test_final_envelope_size_bounds_admission(
    make_core: Callable[[PositiveInt], LocalCacheCore],
    namespace: NamespaceId,
    delta: int,
    expected: AdmissionOutcome,
) -> None:
    documents = [{"value": index} for index in range(12)]
    core = make_core(len(encode_value(documents)) + delta)
    capture = capture_for(core, namespace)
    for document in documents:
        capture.append(document)
    assert capture.finish() is expected
    assert core.snapshot().entry_count == (expected is AdmissionOutcome.ADMITTED)
