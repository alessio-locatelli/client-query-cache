from __future__ import annotations

from typing import TYPE_CHECKING

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.order_sensitive_keys import order_sensitive_key
from client_query_cache._shared.wire import encode_key

if TYPE_CHECKING:
    from client_query_cache._core.keys import NamespaceId
    from client_query_cache._shared_index import SharedOwnerCore
    from client_query_cache._types import NonNegativeInt


def identity_key(identity: object) -> bytes:
    return encode_key(canonicalize(order_sensitive_key(identity)))


def shape_key(shape: object) -> bytes:
    return encode_key(canonicalize(shape))


def assign_slot(
    core: SharedOwnerCore, namespace: NamespaceId
) -> tuple[NonNegativeInt, NonNegativeInt] | None:
    token = core.begin_namespace_metadata_probe(namespace)
    if token is None:
        return None
    metadata = core.namespace_metadata_after_probe(namespace, token)
    assert metadata is not None
    return metadata[2]
