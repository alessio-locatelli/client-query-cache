from __future__ import annotations

from typing import TYPE_CHECKING, Any
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

from client_query_cache._core.codec import decode_value, encode_value
from client_query_cache._core.cursor_capture import CursorCapture
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from tests.codec_helpers import (
    Decimal128ToDecimalDecoder,
    decode_only_decimal_options,
    fail_decimal_encoding,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from decimal import Decimal

    from client_query_cache._core.keys import NamespaceId

pytestmark = pytest.mark.unit
QUERY = ("find", "capture")


def encode_decimal(value: Decimal) -> Decimal128:
    return Decimal128(str(value))


def test_empty_capture_is_admitted(core: CacheCore, namespace: NamespaceId) -> None:
    capture = capture_for(core, namespace)
    assert capture.finish() is AdmissionOutcome.ADMITTED
    lookup = core.lookup_namespace(namespace, QUERY)
    assert lookup.hit
    assert lookup.value == []


@pytest.fixture
def make_core() -> Iterator[Callable[[int], CacheCore]]:
    cores: list[CacheCore] = []  # Tests may create no bounded cores.

    def create(limit: int) -> CacheCore:
        core = CacheCore(
            CacheCoreConfig(shared_budget_bytes=limit * 2, max_entry_bytes=limit)
        )
        cores.append(core)
        return core

    yield create
    for core in cores:
        core.close()


def capture_for(
    core: CacheCore,
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
    core: CacheCore, namespace: NamespaceId, documents: list[dict[str, int]]
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
def test_capture_limit_includes_snapshot_envelope(
    make_core: Callable[[int], CacheCore],
    namespace: NamespaceId,
    delta: int,
    expected: AdmissionOutcome | None,
) -> None:
    document = {"value": "bounded"}
    limit = len(encode_value(document)) + delta
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
    core: CacheCore, namespace: NamespaceId, document: Mapping[str, Any]
) -> None:
    capture = capture_for(core, namespace)
    capture.append({"valid": True})
    capture.append(document)
    capture.append({"also_valid": True})
    assert capture.retained_bytes == 0
    assert capture.finish() is None
    assert not core.lookup_namespace(namespace, QUERY).hit


def test_custom_encoder_failure_discards_native_decoded_candidate(
    core: CacheCore, namespace: NamespaceId
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


def test_abandon_releases_snapshots(core: CacheCore, namespace: NamespaceId) -> None:
    capture = capture_for(core, namespace)
    capture.append({"value": True})
    assert capture.retained_bytes > 0
    capture.abandon()
    assert capture.retained_bytes == 0
    assert capture.finish() is None
    assert not core.lookup_namespace(namespace, QUERY).hit


def make_unavailable(core: CacheCore, namespace: NamespaceId) -> None:
    core.set_database_available(namespace.database, available=False)


def make_unavailable_then_restore(core: CacheCore, namespace: NamespaceId) -> None:
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
def test_capture_keeps_existing_admission_guards(
    core: CacheCore,
    namespace: NamespaceId,
    transition: Callable[[CacheCore, NamespaceId], object],
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
    core: CacheCore, namespace: NamespaceId, options: CodecOptions[Mapping[str, Any]]
) -> None:
    document: dict[str, Any] = {"z": Decimal128("1.25"), "a": {"second": 2, "first": 1}}
    if options.uuid_representation == UuidRepresentation.STANDARD:
        document["uuid"] = UUID("12345678-1234-5678-1234-567812345678")
    decoded = bson.decode(
        bson.encode(document, codec_options=options), codec_options=options
    )
    expected = decode_value(encode_value([decoded], options), options)
    capture = capture_for(core, namespace, options)
    capture.append(decoded)
    assert capture.finish() is AdmissionOutcome.ADMITTED
    actual = core.lookup_namespace(namespace, QUERY, codec_options=options).value
    # Raw documents are compared by encoded bytes; other classes retain field order.
    assert encode_value(actual, options) == encode_value(expected, options)


def test_exact_final_entry_size_is_enforced(
    make_core: Callable[[int], CacheCore], namespace: NamespaceId
) -> None:
    # A single document's stored list envelope exceeds its snapshot envelope.
    documents = [{"value": True}]
    retained = sum(len(encode_value(document)) for document in documents)
    assert len(encode_value(documents)) > retained
    core = make_core(retained)
    capture = capture_for(core, namespace)
    for document in documents:
        capture.append(document)
    assert capture.retained_bytes == retained
    assert capture.finish() is AdmissionOutcome.DECLINED_OVERSIZE
    assert core.snapshot().oversized_bypasses == 1


def test_snapshots_encode_each_document_once(
    core: CacheCore, namespace: NamespaceId, monkeypatch: pytest.MonkeyPatch
) -> None:
    encoded_documents: list[object] = []  # Records can be empty before consumption.
    original_encode = encode_value

    def record(document: object, options: CodecOptions[Mapping[str, Any]]) -> bytes:
        encoded_documents.append(document)
        return original_encode(document, options)

    monkeypatch.setattr("client_query_cache._core.cursor_capture.encode_value", record)
    documents = [{"n": n} for n in range(10)]
    capture = capture_for(core, namespace)
    for document in documents:
        capture.append(document)
    assert capture.finish() is AdmissionOutcome.ADMITTED
    assert encoded_documents == documents
