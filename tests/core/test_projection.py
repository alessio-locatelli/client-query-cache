from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from mongo_client_cache._core.projection import ensure_id_present_for_resolution

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

pytestmark = pytest.mark.unit


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
