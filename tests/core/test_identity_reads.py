from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import bson
import pytest
from bson.binary import UuidRepresentation
from bson.codec_options import CodecOptions

from mongo_client_cache._core.identity_reads import (
    NO_IDENTITY,
    extract_id_identity,
    normalize_identity_for_cache_key,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("filter_query", "expected"),
    [
        pytest.param(None, NO_IDENTITY, id="no-filter"),
        pytest.param({"a": 1}, NO_IDENTITY, id="non-id-field"),
        pytest.param({"_id": 1, "extra": 2}, NO_IDENTITY, id="compound-filter"),
        pytest.param(
            {"_id": {"$in": [1, 2]}}, NO_IDENTITY, id="id-with-query-operator"
        ),
        pytest.param({"_id": "doc-1"}, "doc-1", id="plain-scalar-identity"),
        pytest.param(
            {"_id": {"tenant": "t1", "id": 1}},
            {"tenant": "t1", "id": 1},
            id="compound-id-subdocument",
        ),
        pytest.param({"_id": None}, NO_IDENTITY, id="explicit-null-id"),
        pytest.param("doc-1", "doc-1", id="pymongo-scalar-shorthand"),
        pytest.param(42, 42, id="pymongo-int-shorthand"),
    ],
)
def test_extract_id_identity(filter_query: object, expected: object) -> None:
    assert extract_id_identity(filter_query) == expected


def test_normalize_identity_passes_through_plain_scalars() -> None:
    default: CodecOptions[Any] = CodecOptions()
    assert normalize_identity_for_cache_key("doc-1", default, default) == "doc-1"


def test_normalize_identity_matches_what_the_default_codec_would_decode() -> None:
    identifier = uuid.uuid4()
    read_codec_options: CodecOptions[Any] = CodecOptions(
        uuid_representation=UuidRepresentation.STANDARD
    )
    stream_codec_options: CodecOptions[Any] = CodecOptions()
    stored_bytes = bson.encode({"_id": identifier}, codec_options=read_codec_options)
    stream_decoded = bson.decode(stored_bytes, codec_options=stream_codec_options)[
        "_id"
    ]

    normalized = normalize_identity_for_cache_key(
        identifier, read_codec_options, stream_codec_options
    )

    assert normalized == stream_decoded


def test_normalize_identity_matches_for_a_timezone_aware_datetime() -> None:
    identifier = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
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


def test_normalize_identity_is_a_no_op_when_both_codecs_match() -> None:
    identifier = uuid.uuid4()
    codec_options: CodecOptions[Any] = CodecOptions(
        uuid_representation=UuidRepresentation.STANDARD
    )

    normalized = normalize_identity_for_cache_key(
        identifier, codec_options, codec_options
    )

    assert normalized == identifier


def test_normalize_identity_falls_back_to_the_original_value_when_unencodable() -> None:
    class _Unencodable:
        __slots__ = ()

    identifier = _Unencodable()
    default: CodecOptions[Any] = CodecOptions()

    assert normalize_identity_for_cache_key(identifier, default, default) is identifier
