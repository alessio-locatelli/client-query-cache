from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pymongo.collation import Collation

if TYPE_CHECKING:
    from collections.abc import Mapping

_SIMPLE_LOCALE = "simple"


def normalize_collation(
    collation: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if collation is None:
        return None
    try:
        locale = collation["locale"]
    except KeyError:
        locale = None
    if locale == _SIMPLE_LOCALE:
        return None
    return collation


def collation_document(
    collation: Collation | Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if collation is None:
        return None
    if isinstance(collation, Collation):
        return collation.document
    return dict(collation)
