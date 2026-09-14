from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

_ID_FIELD = "_id"


def without_id(document: Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(document, MutableMapping):
        document.pop(_ID_FIELD, None)
        return document
    return {key: value for key, value in document.items() if key != _ID_FIELD}


def _is_include_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    return True


def ensure_id_present_for_resolution(
    projection: Mapping[str, Any] | Sequence[str] | None,
) -> tuple[Mapping[str, Any] | Sequence[str] | None, bool]:
    if not isinstance(projection, Mapping) or _ID_FIELD not in projection:
        return projection, False
    if _is_include_value(projection[_ID_FIELD]):
        return projection, False
    other_values = [value for key, value in projection.items() if key != _ID_FIELD]
    if any(_is_include_value(value) for value in other_values):
        server_projection = dict(projection)
        server_projection[_ID_FIELD] = 1
        return server_projection, True
    server_projection = {
        key: value for key, value in projection.items() if key != _ID_FIELD
    }
    return server_projection, True
