from __future__ import annotations

import datetime as dt
import re
import struct
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

import bson
import pytest
from bson.binary import Binary
from bson.code import Code
from bson.codec_options import CodecOptions, DatetimeConversion, TypeRegistry
from bson.datetime_ms import DatetimeMS
from bson.dbref import DBRef
from bson.decimal128 import Decimal128
from bson.int64 import Int64
from bson.max_key import MaxKey
from bson.min_key import MinKey
from bson.objectid import ObjectId
from bson.timestamp import Timestamp
from hypothesis import example, given
from hypothesis import strategies as st

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import codec_fingerprint
from client_query_cache._core.count_reads import count_read_options
from client_query_cache._core.find_reads import (
    FindReadShape,
    find_discriminator,
    find_read_shape,
)
from client_query_cache._core.order_sensitive_keys import (
    order_sensitive_discriminator_key,
)
from client_query_cache._shared import wire
from client_query_cache._shared.wire import (
    _EMPTY_IDENTITY,
    _FIND_ENCODER,
    _MAX_CACHED_KEY_BYTES,
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
from client_query_cache._shared_index import FindKeyEncoder
from client_query_cache._types import NonNegativeInt, PositiveInt
from tests.call_counting import count_current_thread_calls
from tests.codec_helpers import Decimal128ToDecimalDecoder

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from faker import Faker

pytestmark = pytest.mark.unit

_INTEGERS = st.integers(min_value=-(2**63), max_value=2**63 - 1)
_SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    _INTEGERS,
    st.floats(allow_nan=False),
    st.text(max_size=8),
    st.binary(max_size=8),
)


@pytest.mark.parametrize("build", [int, Int64], ids=["plain", "explicit-int64"])
@given(value=_INTEGERS)
@example(value=-(1 << 63))
@example(value=(1 << 63) - 1)
@example(value=-(1 << 31))
@example(value=1 << 31)
def test_integer_keys_preserve_bson_wire_bytes(
    build: Callable[[int], int], value: int
) -> None:
    key = build(value)
    expected_bytes = bson.encode({"k": to_wire(key)})
    expected_value = from_wire(bson.decode(expected_bytes)["k"])

    assert encode_key(key) == expected_bytes
    decoded = decode_key(expected_bytes)
    assert decoded == expected_value
    assert type(decoded) is type(expected_value)


@pytest.mark.parametrize(
    "offset", [0, 5, -2, -1], ids=["length", "field", "inner-end", "outer-end"]
)
@given(value=_INTEGERS)
def test_damaged_integer_key_envelopes_remain_protocol_errors(
    offset: int, value: int
) -> None:
    encoded = bytearray(encode_key(value))
    encoded[offset] ^= 1

    with pytest.raises(ProtocolError):
        decode_key(bytes(encoded))


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


@pytest.mark.parametrize(
    "scalar_predicates", [False, True], ids=["operators", "scalar-predicates"]
)
def test_find_shapes_and_codec_profiles_round_trip(
    faker: Faker, *, scalar_predicates: bool
) -> None:
    codec: CodecOptions[Mapping[str, Any]] = CodecOptions(
        tz_aware=True, tzinfo=dt.UTC, type_registry=_EMPTY_IDENTITY._registry
    )
    sku, price = faker.pystr(), faker.pyfloat()
    shape = find_read_shape(
        {"sku": sku, "price": price}
        if scalar_predicates
        else {"sku": sku, "price": {"$gt": price}, "count": Int64(faker.pyint())},
        {"payload": 0},
        {"_id": -1},
        2,
        16,
        collation=None,
        codec=codec_fingerprint(codec),
    )
    canonical = canonicalize(shape.family)
    assert KeyCache(2).find(canonical, shape.limit) == (
        encode_key(canonical),
        encode_key(canonicalize(shape.discriminator)),
    )
    decoded = _roundtrip(canonical)

    assert to_wire(decoded) == to_wire(canonical)
    assert FindReadShape(decoded, shape.limit).source == shape.source
    assert find_discriminator(decoded, shape.limit) == canonicalize(shape.discriminator)
    assert (
        _roundtrip(DatetimeConversion.DATETIME_AUTO) is DatetimeConversion.DATETIME_AUTO
    )


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(ObjectId(), id="object-id"),
        pytest.param(Binary(b"payload", 128), id="binary-subtype"),
        pytest.param(Code("return value", {"value": 1}), id="code-with-scope"),
        pytest.param(dt.datetime(2026, 1, 1, microsecond=1), id="microseconds"),  # noqa: DTZ001 - Exercise naive BSON input.
        pytest.param(dt.datetime(2026, 1, 1, tzinfo=dt.UTC), id="aware"),
        pytest.param(Timestamp(1, 2), id="timestamp"),
        pytest.param(MinKey(), id="minimum-key"),
        pytest.param(MaxKey(), id="maximum-key"),
        pytest.param(DBRef("products", ObjectId()), id="reference"),
        pytest.param(UUID(int=1), id="uuid"),
        pytest.param(DatetimeMS(2**63 - 1), id="extended-datetime"),
        pytest.param(re.compile(r"^value-", re.IGNORECASE), id="regex-text"),
        pytest.param(re.compile(rb"^value-"), id="regex-bytes"),
        pytest.param(Decimal128("1.25"), id="decimal128"),
        pytest.param(
            dt.datetime(2026, 1, 1, 12, 0, 0, 1000),  # noqa: DTZ001 - BSON keys are naive UTC.
            id="millisecond-datetime",
        ),
    ],
)
def test_bson_scalars_keep_their_type(value: object) -> None:
    assert _roundtrip(value) == value
    assert _FIND_ENCODER.encode(value, 16)[0] == encode_key(value)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(2**64, id="int-range"),
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
    with pytest.raises(UnportableKeyError):
        KeyCache(2).find(canonicalize((value,)), 16)


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
        pytest.param({"t": "datetime", "p": 1}, id="datetime-type"),
        pytest.param({"t": "datetime", "p": "bad"}, id="datetime-value"),
        pytest.param({"t": "uuid", "p": "bad"}, id="uuid-type"),
        pytest.param({"t": "uuid", "p": b"bad"}, id="uuid-length"),
        pytest.param({"t": "regex", "p": "bad"}, id="regex-type"),
        pytest.param({"t": "regex", "p": ["a"]}, id="regex-length"),
        pytest.param({"t": "regex", "p": [1, 0]}, id="regex-pattern-type"),
        pytest.param({"t": "regex", "p": ["(", 0]}, id="regex-pattern"),
        pytest.param({"t": "regex", "p": ["a", int(re.LOCALE)]}, id="regex-flags"),
        pytest.param({"t": "regex", "p": ["a", 2**40]}, id="regex-flags-overflow"),
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


@pytest.mark.parametrize("payload_bytes", [_MAX_CACHED_KEY_BYTES, 1024 * 1024])
def test_large_keys_are_usable_without_retention(payload_bytes: PositiveInt) -> None:
    cache = KeyCache(8192)
    retained = canonicalize({"ordinary": "identity"})
    small = cache.encode(retained)
    assert cache.decode(small) == retained
    payload = "x" * payload_bytes
    for index in range(128):
        key = canonicalize({"identifier": f"{index}:{payload}"})
        encoded = cache.encode(key)
        assert cache.decode(encoded) == key
    assert cache._encoded == {retained: small}
    assert cache._decoded == {small: retained}


@pytest.mark.parametrize(
    ("encoded_bytes", "retained"),
    [(_MAX_CACHED_KEY_BYTES, True), (_MAX_CACHED_KEY_BYTES + 1, False)],
)
def test_key_cache_admits_the_encoded_size_boundary(
    encoded_bytes: PositiveInt, *, retained: bool
) -> None:
    overhead = len(encode_key(canonicalize("")))
    key = canonicalize("x" * (encoded_bytes - overhead))
    cache = KeyCache(2)
    encoded = cache.encode(key)
    assert len(encoded) == encoded_bytes
    assert cache.decode(encoded) == key
    assert (key in cache._encoded) is retained
    assert (encoded in cache._decoded) is retained


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


def test_omitted_count_options_keep_their_cross_process_key() -> None:
    options = canonicalize(count_read_options({})["cache_options"])
    assert _roundtrip(options) == options


def test_regex_key_decoding_does_not_print_compile_debug_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    pattern = re.compile(r"private-pattern", re.DEBUG)
    capsys.readouterr()
    decoded = _roundtrip(pattern)
    assert isinstance(decoded, re.Pattern)
    assert decoded.pattern == pattern.pattern
    assert not decoded.flags & re.DEBUG
    assert not capsys.readouterr().out
    assert encode_key(pattern) == encode_key(re.compile(r"private-pattern"))


@pytest.mark.parametrize("build", [int, Int64], ids=["plain", "explicit-int64"])
@given(value=_VALUES, limit=_INTEGERS)
@example(value={"field": [True, None, "zero\x00inside"]}, limit=0)
def test_native_find_keys_match_python_bytes(
    build: Callable[[int], int], value: object, limit: int
) -> None:
    family = canonicalize(order_sensitive_discriminator_key(value))
    signed_limit = build(limit)
    assert KeyCache(2).find(family, signed_limit) == (
        encode_key(family),
        encode_key(find_discriminator(family, signed_limit)),
    )


@pytest.mark.parametrize("limit", [False, True], ids=["false", "true"])
def test_native_find_keys_preserve_boolean_discriminators(*, limit: bool) -> None:
    family = canonicalize({"field": "value"})
    assert KeyCache(2).find(family, limit) == (
        encode_key(family),
        encode_key(find_discriminator(family, limit)),
    )


@pytest.mark.parametrize("capacity", [1, 2, 8])
@given(
    operations=st.lists(st.tuples(st.booleans(), _INTEGERS), min_size=2, max_size=16)
)
@example(operations=[(True, 0), (False, 0), (True, 1)])
@example(operations=[(False, 0), (True, 0), (False, 1)])
def test_find_and_generic_keys_share_the_retention_budget(
    capacity: PositiveInt, operations: list[tuple[bool, int]]
) -> None:
    cache = KeyCache(capacity)
    for is_find, value in operations:
        if is_find:
            family = canonicalize({"field": value})
            encoded = cache.find(family, 16)
            assert encoded == (
                encode_key(family),
                encode_key(find_discriminator(family, 16)),
            )
            assert (cache.find(family, 16) is encoded) is (capacity >= 2)
        else:
            assert cache.encode(value) == encode_key(value)
        assert len(cache._encoded) + len(cache._finds) <= capacity


@pytest.mark.parametrize("extra", [0, 1], ids=["at-bound", "above-bound"])
def test_find_key_pairs_apply_the_per_key_size_bound(extra: NonNegativeInt) -> None:
    cache = KeyCache(2)
    overhead = len(cache.find("", 16)[1])
    family = "x" * (_MAX_CACHED_KEY_BYTES - overhead + extra)
    keys = cache.find(family, 16)
    assert len(keys[1]) == _MAX_CACHED_KEY_BYTES + extra
    assert keys == (encode_key(family), encode_key(find_discriminator(family, 16)))
    assert (canonicalize((family, 16)) in cache._finds) is (extra == 0)
    assert cache.find(family, 16)[0] is keys[0]


def test_oversized_find_families_remain_usable_without_retention() -> None:
    cache = KeyCache(2)
    family = "x" * _MAX_CACHED_KEY_BYTES
    keys = cache.find(family, 16)
    assert keys == (encode_key(family), encode_key(find_discriminator(family, 16)))
    assert cache.find(family, 16) == keys
    assert not cache._encoded
    assert not cache._finds


def test_native_find_keys_preserve_unicode_encoding_errors() -> None:
    family = ("\ud800",)
    with pytest.raises(UnicodeEncodeError):
        encode_key(family)
    with pytest.raises(UnicodeEncodeError):
        KeyCache(2).find(family, 16)


def test_native_tuple_encoding_obeys_the_python_native_stack_guard() -> None:
    family: object = "leaf"
    for _ in range(100_000):
        family = (family,)
    with pytest.raises(RecursionError):
        _FIND_ENCODER.encode(family, 16)


def test_native_find_encoder_visits_specialized_family_scalars_once(
    monkeypatch: pytest.MonkeyPatch, faker: Faker
) -> None:
    family = canonicalize((Int64(faker.pyint()), Int64(faker.pyint())))
    expected = (encode_key(family), encode_key(find_discriminator(family, 16)))
    scalars = count_current_thread_calls(monkeypatch, wire, "encode_key")
    encoder = FindKeyEncoder(wire._TAG_NAMES, wire.encode_key)
    assert encoder.encode(family, 16) == expected
    assert scalars.count == 2


def test_find_limits_reuse_the_encoded_family(faker: Faker) -> None:
    cache = KeyCache(8)
    family = canonicalize({"field": faker.pystr()})
    first = cache.find(family, 16)
    second = cache.find(family, 8)
    assert first[0] is second[0]
    assert first[1] != second[1]
    assert len(cache._encoded) == 1
    assert len(cache._finds) == 2


@pytest.mark.parametrize(
    "encoded",
    [b"", b"short", bson.encode({"wrong": 1}), b"\x08\x00\x00\x00\x0ak\x00\xff"],
    ids=["empty", "short", "field-name", "terminator"],
)
def test_native_find_wrapping_rejects_invalid_envelopes(encoded: bytes) -> None:
    with pytest.raises(ValueError, match="invalid encoded key envelope"):
        _FIND_ENCODER.wrap(encoded, 16)
