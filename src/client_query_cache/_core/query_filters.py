from __future__ import annotations

from client_query_cache._core.order_sensitive_keys import (
    order_sensitive_discriminator_key,
)


class _FilterTag:
    __slots__ = ()


_SCALAR_PREDICATES = _FilterTag()
_SCALAR_TYPES = (bool, int, float, str)


def find_filter_key(filter_document: object) -> object:
    if type(filter_document) is dict and all(
        type(field) is str
        and not field.startswith("$")
        and (value is None or type(value) in _SCALAR_TYPES)
        for field, value in filter_document.items()
    ):
        return (
            _SCALAR_PREDICATES,
            order_sensitive_discriminator_key(dict(sorted(filter_document.items()))),
        )
    return order_sensitive_discriminator_key(filter_document)
