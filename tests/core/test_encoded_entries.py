from __future__ import annotations

from contextlib import nullcontext
from decimal import Decimal
from typing import TYPE_CHECKING, Any, override

import pytest
from bson.codec_options import CodecOptions, TypeEncoder, TypeRegistry
from bson.decimal128 import Decimal128

from client_query_cache import CacheCore
from client_query_cache._core.codec import encode_value
from client_query_cache._core.entries import AdmissionOutcome, LookupResult
from client_query_cache._core.find_reads import find_read_shape
from tests.codec_helpers import decode_only_decimal_options
from tests.core.conftest import evict_by_pressure

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from contextlib import AbstractContextManager

    from client_query_cache._core.contracts import IdentityCaptureView
    from client_query_cache._core.find_reads import FindReadShape
    from client_query_cache._core.keys import NamespaceId
    from tests.core.conftest import PinnedAlias

pytestmark = pytest.mark.unit

_PRICE = Decimal("12.50")


class _DecimalEncoder(TypeEncoder):
    python_type = Decimal

    @override
    def transform_python(self, value: Decimal) -> Decimal128:
        return Decimal128(value)


class _FailingEncoder(TypeEncoder):
    python_type = Decimal

    @override
    def transform_python(self, value: Decimal) -> Decimal128:
        message = f"application encoder rejected {value}"
        raise RuntimeError(message)


def _codec() -> CodecOptions[Mapping[str, Any]]:
    return CodecOptions(type_registry=TypeRegistry([_DecimalEncoder()]))


def _find_shape(limit: int) -> FindReadShape:
    return find_read_shape(
        {"family": "catalogue"},
        None,
        {"_id": 1},
        0,
        limit,
        collation=None,
        codec="codec",
    )


def _admit_namespace(
    core: CacheCore, namespace: NamespaceId, *, encoded: bool
) -> AdmissionOutcome:
    capture = core.capture_namespace_generation(namespace)
    value = [{"price": _PRICE}]
    if encoded:
        return core.admit_namespace_encoded(
            capture, "shape", encode_value(value, _codec())
        )
    return core.admit_namespace(capture, "shape", value, codec_options=_codec())


def _admit_find(
    core: CacheCore, namespace: NamespaceId, *, encoded: bool
) -> AdmissionOutcome:
    source = _find_shape(10)
    capture = core.capture_namespace_generation(namespace)
    value = [{"price": _PRICE}]
    if encoded:
        return core.admit_namespace_encoded(
            capture,
            source.discriminator,
            encode_value(value, _codec()),
            find_source=source.source,
        )
    return core.admit_namespace(
        capture,
        source.discriminator,
        value,
        codec_options=_codec(),
        find_source=source.source,
    )


_ADMISSIONS = [
    pytest.param(
        _admit_namespace,
        lambda core, namespace: core.lookup_namespace_encoded(namespace, "shape"),
        lambda core, namespace, codec: core.lookup_namespace(
            namespace, "shape", codec_options=codec
        ),
        id="namespace",
    ),
    pytest.param(
        _admit_find,
        lambda core, namespace: core.lookup_find_encoded(namespace, _find_shape(5)),
        lambda core, namespace, codec: core.lookup_find(
            namespace, _find_shape(5), codec_options=codec
        ),
        id="find",
    ),
]


@pytest.mark.parametrize(("admit", "lookup_encoded", "lookup"), _ADMISSIONS)
def test_encoded_admission_stores_the_bytes_of_the_codec_transformed_value(
    namespace: NamespaceId,
    admit: Callable[..., AdmissionOutcome],
    lookup_encoded: Callable[[CacheCore, NamespaceId], object],
    lookup: Callable[[CacheCore, NamespaceId, object], LookupResult],
) -> None:
    standalone, encoded = CacheCore(), CacheCore()

    assert admit(standalone, namespace, encoded=False) is AdmissionOutcome.ADMITTED
    assert admit(encoded, namespace, encoded=True) is AdmissionOutcome.ADMITTED

    assert lookup_encoded(encoded, namespace) == lookup_encoded(standalone, namespace)
    decoding = decode_only_decimal_options()
    assert lookup(encoded, namespace, decoding) == lookup(
        standalone, namespace, decoding
    )
    assert lookup(encoded, namespace, decoding).value is not None


@pytest.mark.parametrize(
    ("admit", "invalidate"),
    [
        pytest.param(
            _admit_namespace,
            lambda core, namespace: core.record_write(namespace, "other"),
            id="namespace-write",
        ),
        pytest.param(
            _admit_find,
            lambda core, namespace: core.set_database_available(
                namespace.database, available=False
            ),
            id="availability",
        ),
    ],
)
@pytest.mark.parametrize("core", [True], indirect=True, ids=["telemetry"])
def test_encoded_admission_rejects_a_capture_from_an_older_generation(
    core: CacheCore,
    namespace: NamespaceId,
    admit: Callable[..., AdmissionOutcome],
    invalidate: Callable[[CacheCore, NamespaceId], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("begin_identity_admission", "capture_namespace_generation"):
        original = getattr(CacheCore, name)

        def capture_then_invalidate(
            self: CacheCore, *args: object, _original: Callable[..., object] = original
        ) -> object:
            captured = _original(self, *args)
            invalidate(self, namespace)
            return captured

        monkeypatch.setattr(CacheCore, name, capture_then_invalidate)

    assert admit(core, namespace, encoded=True) in {
        AdmissionOutcome.DECLINED_STALE,
        AdmissionOutcome.DECLINED_UNAVAILABLE,
    }
    assert core.snapshot().entry_count == 0


_FAILING_CODEC: CodecOptions[Mapping[str, Any]] = CodecOptions(
    type_registry=TypeRegistry([_FailingEncoder()])
)


@pytest.mark.parametrize(
    ("admit", "outcome"),
    [
        pytest.param(
            lambda core, capture: core.admit_identity(capture, "full", 10**20),
            nullcontext(),
            id="overflow",
        ),
        pytest.param(
            lambda core, capture: core.admit_identity(capture, "full", object()),
            nullcontext(),
            id="unencodable",
        ),
        pytest.param(
            lambda core, capture: core.admit_identity(
                capture, "full", {"price": _PRICE}, codec_options=_FAILING_CODEC
            ),
            pytest.raises(RuntimeError, match="application encoder rejected"),
            id="encoder-raises",
        ),
    ],
)
def test_identity_admission_releases_its_capture(
    pinned_alias: PinnedAlias,
    admit: Callable[[CacheCore, IdentityCaptureView], object],
    outcome: AbstractContextManager[object],
) -> None:
    core, namespace, identity, value, capture = pinned_alias

    with outcome:
        admit(core, capture)

    evict_by_pressure(core, namespace, value)
    assert core.resolve_alias(namespace, "code", identity, None) is None


@pytest.mark.parametrize("core", [True], indirect=True, ids=["telemetry"])
def test_encoded_find_admission_replaces_the_resident_source(
    core: CacheCore, namespace: NamespaceId
) -> None:
    _admit_marked_find(core, namespace, 1)
    core.record_write(namespace, "unrelated")
    _admit_marked_find(core, namespace, 2)

    assert core.snapshot().entry_count == 1
    assert core.lookup_find(namespace, _find_shape(5)).value == [2]


def _admit_marked_find(core: CacheCore, namespace: NamespaceId, marker: int) -> None:
    source = _find_shape(10)
    outcome = core.admit_namespace_encoded(
        core.capture_namespace_generation(namespace),
        source.discriminator,
        encode_value([marker]),
        find_source=source.source,
    )
    assert outcome is AdmissionOutcome.ADMITTED


@pytest.mark.parametrize("core", [True], indirect=True, ids=["telemetry"])
def test_encoded_namespace_lookup_defers_a_requested_miss(
    core: CacheCore, namespace: NamespaceId
) -> None:
    deferred = core.lookup_namespace_encoded(namespace, "shape", defer_miss=True)

    assert isinstance(deferred, LookupResult)
    assert deferred.deferred_miss
    assert core.snapshot().misses == 0
