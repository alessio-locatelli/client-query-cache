from __future__ import annotations

import datetime
import struct
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import bson
import pytest
from bson.codec_options import CodecOptions, DatetimeConversion, TypeRegistry
from bson.decimal128 import Decimal128
from bson.int64 import Int64
from bson.objectid import ObjectId
from hypothesis import given
from hypothesis import strategies as st

from benchmarks.stream_cost.shared_cache.wire import (
    KeyCache,
    ProtocolError,
    UnportableKeyError,
    decode_frame,
    decode_key,
    encode_frame,
    encode_key,
    frame_length,
    from_wire,
    to_wire,
)
from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import codec_fingerprint
from client_query_cache._core.find_reads import find_read_shape
from client_query_cache._core.order_sensitive_keys import (
    order_sensitive_discriminator_key,
)
from tests.codec_helpers import Decimal128ToDecimalDecoder

if TYPE_CHECKING:
    from collections.abc import Mapping

    from faker import Faker

pytestmark = pytest.mark.unit

_SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**63), max_value=2**63 - 1),
    st.floats(allow_nan=False),
    st.text(max_size=8),
    st.binary(max_size=8),
)
_VALUES = st.recursive(
    _SCALARS,
    lambda children: (
        st.lists(children, max_size=3)
        | st.dictionaries(st.text(max_size=4), children, max_size=3)
    ),
    max_leaves=12,
)


def _roundtrip(value: object) -> object:
    return from_wire(bson.decode(bson.encode({"v": to_wire(value)}))["v"])


@given(_VALUES)
def test_canonical_keys_round_trip_through_bson(value: object) -> None:
    canonical = canonicalize(order_sensitive_discriminator_key(value))

    assert _roundtrip(canonical) == canonical


def test_find_shapes_and_codec_profiles_round_trip(faker: Faker) -> None:
    codec: CodecOptions[Mapping[str, Any]] = CodecOptions(
        tz_aware=True, tzinfo=datetime.UTC
    )
    shape = find_read_shape(
        {"sku": faker.pystr(), "price": {"$gt": 1.5}, "count": Int64(3)},
        {"payload": 0},
        {"_id": -1},
        2,
        16,
        collation=None,
        codec=codec_fingerprint(codec),
    )
    canonical = canonicalize(shape.family)

    assert to_wire(_roundtrip(canonical)) == to_wire(canonical)
    assert (
        _roundtrip(DatetimeConversion.DATETIME_AUTO) is DatetimeConversion.DATETIME_AUTO
    )


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(ObjectId(), id="object-id"),
        pytest.param(Decimal128("1.25"), id="decimal128"),
        pytest.param(
            datetime.datetime(2026, 1, 1, 12, 0, 0, 1000),  # noqa: DTZ001 - BSON keys are naive UTC.
            id="millisecond-datetime",
        ),
    ],
)
def test_bson_scalars_keep_their_type(value: object) -> None:
    assert _roundtrip(value) == value


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(2**64, id="int-range"),
        pytest.param(
            datetime.datetime(2026, 1, 1, microsecond=1),  # noqa: DTZ001 - BSON keys are naive UTC.
            id="microseconds",
        ),
        pytest.param(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC), id="aware"),
        pytest.param(Decimal("1.5"), id="native-decimal"),
        pytest.param(frozenset({1}), id="frozenset"),
        pytest.param(
            codec_fingerprint(
                CodecOptions(type_registry=TypeRegistry([Decimal128ToDecimalDecoder()]))
            ),
            id="custom-registry",
        ),
    ],
)
def test_unportable_keys_are_rejected(value: object) -> None:
    with pytest.raises(UnportableKeyError):
        to_wire(canonicalize(value))


@pytest.mark.parametrize(
    "node",
    [
        pytest.param({"t": "tuple"}, id="missing-payload"),
        pytest.param({"t": "tuple", "p": 1}, id="tuple-payload"),
        pytest.param({"t": "int", "p": "1"}, id="integer-payload"),
        pytest.param({"t": "int64", "p": True}, id="boolean-payload"),
        pytest.param({"t": "datetime-conversion", "p": 99}, id="conversion"),
        pytest.param({"t": "class", "p": "SON"}, id="class"),
        pytest.param({"t": "registry", "p": "custom"}, id="registry"),
        pytest.param({"t": "tzinfo", "p": "local"}, id="tzinfo"),
        pytest.param({"t": "tag", "p": "unknown"}, id="tag"),
        pytest.param({"t": "unknown", "p": 1}, id="node"),
    ],
)
def test_malformed_canonical_nodes_are_protocol_errors(node: dict[str, object]) -> None:
    with pytest.raises(ProtocolError):
        from_wire(node)


def test_frames_round_trip_and_enforce_their_limits() -> None:
    frame = encode_frame({"v": 1, "id": 7, "op": "observe"})

    assert frame_length(frame[:4], 1024) == len(frame) - 4
    assert decode_frame(frame[4:]) == {"v": 1, "id": 7, "op": "observe"}
    with pytest.raises(ProtocolError, match="limit"):
        frame_length(struct.pack("<I", 2048), 1024)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"\x05\x00\x00\x00\xff", id="invalid"),
        pytest.param(bson.encode({"id": 1}), id="no-version"),
        pytest.param(bson.encode({"v": 2}), id="version"),
    ],
)
def test_invalid_frames_are_protocol_errors(body: bytes) -> None:
    with pytest.raises(ProtocolError):
        decode_frame(body)


def test_key_cache_reuses_bounded_encodings(faker: Faker) -> None:
    cache = KeyCache(2)
    shapes = [canonicalize({"field": faker.unique.pystr()}) for _ in range(3)]

    encoded = [cache.encode(shape) for shape in shapes]

    assert cache.encode(shapes[2]) is encoded[2]
    assert [cache.decode(item) for item in encoded] == shapes
    assert cache.decode(encoded[2]) == shapes[2]


@pytest.mark.parametrize(
    "encoded",
    [
        pytest.param(7, id="not-bytes"),
        pytest.param(["unhashable"], id="unhashable"),
        pytest.param(b"\x05\x00\x00\x00\xff", id="invalid"),
        pytest.param(bson.encode({"x": 1}), id="no-value"),
    ],
)
def test_malformed_cache_keys_are_protocol_errors(encoded: object) -> None:
    with pytest.raises(ProtocolError):
        KeyCache(4).decode(encoded)


def test_identity_keys_decode_without_the_cache() -> None:
    assert decode_key(encode_key(canonicalize({"_id": 1}))) == canonicalize({"_id": 1})
