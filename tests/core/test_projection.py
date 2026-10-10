from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

import bson
import pytest
from bson.codec_options import CodecOptions
from bson.raw_bson import RawBSONDocument
from hypothesis import given
from hypothesis import strategies as st

from client_query_cache._core.projection import (
    ensure_id_present_for_resolution,
    without_id,
)
from client_query_cache._types import BsonDict

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

pytestmark = pytest.mark.unit

_PROJECTION_VALUES = st.sampled_from((0, 1, True, False))
_INCLUSION_VALUES = st.sampled_from((1, True))
_EXCLUSION_VALUES = st.sampled_from((0, False))
_FIELD_NAMES = st.text(min_size=1, max_size=8).filter(lambda name: name != "_id")


@st.composite
def _projection_dicts(draw: st.DrawFn) -> BsonDict:
    other_values = draw(st.sampled_from((_INCLUSION_VALUES, _EXCLUSION_VALUES)))
    fields = draw(st.dictionaries(_FIELD_NAMES, other_values, max_size=5))
    projection: BsonDict = dict(fields)
    if draw(st.booleans()):
        projection["_id"] = draw(_PROJECTION_VALUES)
    return projection


@pytest.mark.parametrize(
    "projection",
    [
        pytest.param(None, id="no-projection"),
        pytest.param(["name", "email"], id="sequence-projection"),
        pytest.param({"name": 1}, id="inclusion-without-mentioning-id"),
        pytest.param({"secret": 0}, id="exclusion-without-mentioning-id"),
        pytest.param({"_id": 1, "name": 1}, id="inclusion-with-id-included"),
        pytest.param({"_id": True, "name": 1}, id="inclusion-with-id-included-bool"),
    ],
)
def test_projection_already_including_id_is_left_untouched(
    projection: Mapping[str, Any] | Sequence[str] | None,
) -> None:
    server_projection, exclude_id = ensure_id_present_for_resolution(projection)

    assert server_projection == projection
    assert exclude_id is False


@pytest.mark.parametrize(
    "projection",
    [
        pytest.param({"_id": 0, "name": 1}, id="plain-inclusion-value"),
        pytest.param(
            {"_id": 0, "items": {"$slice": 5}}, id="operator-style-inclusion-value"
        ),
    ],
)
def test_inclusion_style_projection_excluding_id_gets_id_overridden_to_included(
    projection: Mapping[str, Any],
) -> None:
    server_projection, exclude_id = ensure_id_present_for_resolution(projection)

    assert server_projection == {**projection, "_id": 1}
    assert exclude_id is True


@pytest.mark.parametrize(
    "projection",
    [
        pytest.param({"_id": 0, "secret": 0}, id="exclusion-style-with-other-field"),
        pytest.param({"_id": 0}, id="id-only-exclusion"),
        pytest.param({"_id": False}, id="id-only-exclusion-bool"),
    ],
)
def test_exclusion_style_projection_excluding_id_drops_the_id_exclusion(
    projection: Mapping[str, Any],
) -> None:
    server_projection, exclude_id = ensure_id_present_for_resolution(projection)

    server_mapping = cast("Mapping[str, Any]", server_projection)
    assert "_id" not in server_mapping
    assert exclude_id is True
    assert server_mapping == {
        key: value for key, value in projection.items() if key != "_id"
    }


def test_never_produces_a_mixed_inclusion_exclusion_projection() -> None:
    server_projection, _exclude_id = ensure_id_present_for_resolution(
        {"_id": 0, "secret": 0}
    )

    values = set(cast("Mapping[str, Any]", server_projection).values())
    assert not (any(value for value in values) and any(not value for value in values))


@given(_projection_dicts())
def test_ensure_id_present_for_resolution_never_mixes_inclusion_and_exclusion(
    projection: BsonDict,
) -> None:
    server_projection, _exclude_id = ensure_id_present_for_resolution(projection)

    assert isinstance(server_projection, dict)
    other_values = [value for key, value in server_projection.items() if key != "_id"]
    has_inclusion = any(value for value in other_values)
    has_exclusion = any(not value for value in other_values)
    assert not (has_inclusion and has_exclusion)


_UNENCODABLE_VALUE = object()
_OUT_OF_RANGE_INT = 10**20
_RAW_BSON_CODEC_OPTIONS = CodecOptions(document_class=RawBSONDocument)


@pytest.mark.parametrize(
    ("document", "codec_options", "expected", "expected_type", "same_object"),
    [
        pytest.param(
            {"_id": "doc-1", "name": "Ada"},
            None,
            {"name": "Ada"},
            dict,
            True,
            id="mutable-mapping",
        ),
        pytest.param(
            MappingProxyType({"_id": "doc-1", "name": "Ada"}),
            None,
            {"name": "Ada"},
            dict,
            False,
            id="immutable-mapping-without-codec-options",
        ),
        pytest.param(
            RawBSONDocument(
                bson.encode({"_id": "doc-1", "name": "Ada"}),
                codec_options=_RAW_BSON_CODEC_OPTIONS,
            ),
            _RAW_BSON_CODEC_OPTIONS,
            {"name": "Ada"},
            RawBSONDocument,
            False,
            id="custom-document-class-with-codec-options",
        ),
        pytest.param(
            MappingProxyType({"_id": "doc-1", "name": _UNENCODABLE_VALUE}),
            CodecOptions(),
            {"name": _UNENCODABLE_VALUE},
            dict,
            False,
            id="falls-back-when-re-encoding-fails",
        ),
        pytest.param(
            MappingProxyType({"_id": "doc-1", "name": _OUT_OF_RANGE_INT}),
            CodecOptions(),
            {"name": _OUT_OF_RANGE_INT},
            dict,
            False,
            id="falls-back-when-re-encoding-overflows",
        ),
    ],
)
def test_without_id_strips_the_id_field(
    document: Mapping[str, Any],
    codec_options: CodecOptions[Any] | None,
    expected: Mapping[str, Any],
    expected_type: type,
    same_object: bool,
) -> None:
    stripped_document = without_id(document, codec_options)

    assert isinstance(stripped_document, expected_type)
    assert (stripped_document is document) is same_object
    assert dict(stripped_document.items()) == expected
