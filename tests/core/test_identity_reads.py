from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, override

import bson
import pytest
from bson.binary import UuidRepresentation
from bson.codec_options import CodecOptions, TypeDecoder, TypeRegistry
from bson.int64 import Int64
from bson.regex import Regex
from bson.son import SON
from hypothesis import example, given
from hypothesis import strategies as st

from client_query_cache._core.identity_reads import (
    NO_IDENTITY,
    extract_id_anchor,
    normalize_identity_for_cache_key,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from faker import Faker

pytestmark = pytest.mark.unit


class _IntegerDecoder(TypeDecoder):
    bson_type = int

    @override
    def transform_bson(self, value: int) -> str:
        return str(value)


class _Unencodable:
    __slots__ = ()


@pytest.fixture(scope="module", params=("same", "distinct", "decoder", "ordered"))
def integer_codecs(
    request: pytest.FixtureRequest,
) -> tuple[CodecOptions[Any], CodecOptions[Any]]:
    match request.param:
        case "distinct":
            return CodecOptions(), CodecOptions()
        case "decoder":
            options: CodecOptions[Any] = CodecOptions(
                type_registry=TypeRegistry([_IntegerDecoder()])
            )
        case "ordered":
            options = CodecOptions(document_class=SON)
        case _:
            options = CodecOptions()
    return options, options


@pytest.mark.parametrize("build", [int, Int64], ids=["plain", "explicit-int64"])
@given(value=st.integers(min_value=-(1 << 63), max_value=(1 << 63) - 1))
@example(value=-(1 << 31) - 1)
@example(value=-(1 << 31))
@example(value=(1 << 31) - 1)
@example(value=1 << 31)
def test_integer_identity_normalization_matches_bson(
    integer_codecs: tuple[CodecOptions[Any], CodecOptions[Any]],
    build: Callable[[int], int],
    value: int,
) -> None:
    read_options, stream_options = integer_codecs
    identifier = build(value)
    encoded = bson.encode({"_id": identifier}, codec_options=read_options)
    expected = bson.decode(encoded, codec_options=stream_options)["_id"]

    normalized = normalize_identity_for_cache_key(
        identifier, read_options, stream_options
    )

    assert normalized == expected
    assert type(normalized) is type(expected)


@pytest.mark.parametrize(
    ("filter_query", "expected"),
    [
        pytest.param(None, NO_IDENTITY, id="no-filter"),
        pytest.param({"a": 1}, NO_IDENTITY, id="non-id-field"),
        pytest.param({"_id": 1, "extra": 2}, 1, id="compound-filter"),
        pytest.param({"extra": 2, "_id": 1, "last": 3}, 1, id="id-between-predicates"),
        pytest.param(
            {"_id": {"$in": [1, 2]}, "a": 1}, NO_IDENTITY, id="compound-operator"
        ),
        pytest.param({"_id": None, "a": 1}, NO_IDENTITY, id="compound-null"),
        pytest.param({"_id": Regex("^doc-"), "a": 1}, NO_IDENTITY, id="compound-regex"),
        pytest.param(
            {"_id": {"$in": [1, 2]}}, NO_IDENTITY, id="id-with-query-operator"
        ),
        pytest.param({"_id": "doc-1"}, "doc-1", id="plain-scalar-identity"),
        pytest.param(MappingProxyType({"_id": 1}), 1, id="read-only-identity-filter"),
        pytest.param(
            MappingProxyType({"_id": 1, "extra": 2}),
            1,
            id="read-only-compound-filter",
        ),
        pytest.param(
            {"_id": {"tenant": "t1", "id": 1}},
            {"tenant": "t1", "id": 1},
            id="compound-id-subdocument",
        ),
        pytest.param({"_id": None}, NO_IDENTITY, id="explicit-null-id"),
        pytest.param("doc-1", "doc-1", id="pymongo-scalar-shorthand"),
        pytest.param(42, 42, id="pymongo-int-shorthand"),
        pytest.param(
            {"_id": re.compile(r"^doc-")}, NO_IDENTITY, id="id-with-python-regex"
        ),
        pytest.param({"_id": Regex("^doc-")}, NO_IDENTITY, id="id-with-bson-regex"),
        pytest.param(re.compile(r"^doc-"), NO_IDENTITY, id="python-regex-shorthand"),
        pytest.param(Regex("^doc-"), NO_IDENTITY, id="bson-regex-shorthand"),
    ],
)
def test_extract_id_anchor(filter_query: object, expected: object) -> None:
    identity, remainder = extract_id_anchor(filter_query)
    assert identity == expected
    if expected is NO_IDENTITY or not isinstance(filter_query, Mapping):
        assert remainder == {}
    else:
        assert tuple(remainder.items()) == tuple(
            (key, value) for key, value in filter_query.items() if key != "_id"
        )


def test_normalize_identity_passes_through_plain_scalars(faker: Faker) -> None:
    identifier = faker.pystr()
    default: CodecOptions[Any] = CodecOptions()
    assert normalize_identity_for_cache_key(identifier, default, default) == identifier


@pytest.mark.parametrize("matching_codecs", [False, True], ids=["default", "matching"])
def test_normalize_uuid_identity_matches_bson(
    faker: Faker, matching_codecs: bool
) -> None:
    identifier = faker.uuid4(cast_to=None)
    read_codec_options: CodecOptions[Any] = CodecOptions(
        uuid_representation=UuidRepresentation.STANDARD
    )
    stream_codec_options = read_codec_options if matching_codecs else CodecOptions()
    stored_bytes = bson.encode({"_id": identifier}, codec_options=read_codec_options)
    stream_decoded = bson.decode(stored_bytes, codec_options=stream_codec_options)[
        "_id"
    ]

    normalized = normalize_identity_for_cache_key(
        identifier, read_codec_options, stream_codec_options
    )

    assert normalized == stream_decoded


def test_normalize_identity_matches_for_a_timezone_aware_datetime(faker: Faker) -> None:
    identifier = faker.date_time(tzinfo=UTC)
    read_codec_options: CodecOptions[Any] = CodecOptions(tz_aware=True)
    stream_codec_options: CodecOptions[Any] = CodecOptions()
    stored_bytes = bson.encode({"_id": identifier}, codec_options=read_codec_options)
    stream_decoded = bson.decode(stored_bytes, codec_options=stream_codec_options)[
        "_id"
    ]

    normalized = normalize_identity_for_cache_key(
        identifier, read_codec_options, stream_codec_options
    )

    assert normalized == stream_decoded
    assert isinstance(normalized, datetime)
    assert normalized.tzinfo is None


def test_normalize_identity_falls_back_to_the_original_value_when_unencodable() -> None:
    identifier = _Unencodable()
    default: CodecOptions[Any] = CodecOptions()

    assert normalize_identity_for_cache_key(identifier, default, default) is identifier
