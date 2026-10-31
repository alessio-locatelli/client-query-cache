from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

import pytest
from bson.codec_options import CodecOptions
from bson.raw_bson import RawBSONDocument
from bson.son import SON
from bson.tz_util import FixedOffset

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import codec_fingerprint, codec_identity_key
from client_query_cache._core.find_one_reads import (
    find_one_options_cacheable,
    find_one_read_shape,
    find_one_read_shape_key,
)
from tests.key_inputs import outcome, same_outcome

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "collation",
    [
        pytest.param({}, id="missing-locale-type-error"),
        pytest.param({"locale": 1}, id="non-string-locale-type-error"),
        pytest.param(
            {"locale": "en", "caseLevel": 1}, id="non-boolean-case-level-type-error"
        ),
        pytest.param(
            {"locale": "en", "strength": "high"}, id="non-numeric-strength-value-error"
        ),
    ],
)
def test_collation_rejected_by_pymongo_is_not_cacheable(
    collation: dict[str, Any],
) -> None:
    assert find_one_options_cacheable(None, collation) is False


@pytest.mark.parametrize(
    ("left", "right", "equal"),
    [(None, {}, True), (None, {"a": 1}, False), ({"a": 1}, {"a": 1.0}, False)],
    ids=["empty-remainder", "nonempty-remainder", "bson-numeric-types"],
)
def test_find_one_read_shape_retains_remainder(
    left: dict[str, object] | None,
    right: dict[str, object],
    *,
    equal: bool,
) -> None:
    default_shape = find_one_read_shape(None, None, None, "codec")
    left_shape = (
        default_shape
        if left is None
        else find_one_read_shape(None, None, None, "codec", left)
    )
    right_shape = find_one_read_shape(None, None, None, "codec", right)
    assert (left_shape == right_shape) is equal


class _UnhashableZone(FixedOffset):
    __hash__ = None  # type: ignore[assignment]


@pytest.mark.parametrize(
    "read_shape", [find_one_read_shape_key, find_one_read_shape], ids=["key", "pending"]
)
@pytest.mark.parametrize(
    "options",
    [
        CodecOptions(),
        CodecOptions(document_class=SON),
        CodecOptions(document_class=RawBSONDocument),
        CodecOptions(tz_aware=True, tzinfo=dt.UTC),
        CodecOptions(tz_aware=True, tzinfo=_UnhashableZone(0, "UTC")),
    ],
    ids=["dict", "ordered", "raw", "timezone", "unhashable-timezone"],
)
def test_precomputed_codec_keys_preserve_read_shape_keys(
    read_shape: Callable[..., object], options: CodecOptions[Any]
) -> None:
    def key(codec: object) -> object:
        return canonicalize(read_shape(None, [("a", 1)], None, codec))

    assert same_outcome(
        outcome(key, codec_identity_key(options)),
        outcome(key, codec_fingerprint(options)),
    )
