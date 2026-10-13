from __future__ import annotations

import socket
import time
from functools import lru_cache
from typing import TYPE_CHECKING

from benchmarks.stream_cost.shared_cache.attachment import (
    EndpointCounters,
    _SyncConnection,
)
from benchmarks.stream_cost.shared_cache.wire import encode_frame, encode_key
from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.order_sensitive_keys import order_sensitive_key
from client_query_cache._types import NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Set as AbstractSet

    from benchmarks.stream_cost.shared_cache.adapters import (
        AsyncSharedCacheManager,
        SharedCacheManager,
    )
    from benchmarks.stream_cost.shared_cache.attachment import AttachmentConfig
    from client_query_cache._types import BsonDict


@lru_cache(maxsize=1024)
def local_key(key: NonNegativeInt) -> bytes:
    return encode_key(canonicalize(order_sensitive_key(key)))


def local_read(
    manager: SharedCacheManager[BsonDict] | AsyncSharedCacheManager[BsonDict],
    database: str,
    collection: str,
    key: NonNegativeInt,
) -> bytes | None:
    namespace = NamespaceId(database, collection)
    local = manager.local
    assert local is not None
    database_slot, slot, _incarnation = manager._slots[namespace]
    return local.reader.lookup(
        database_slot,
        slot,
        manager._metadata[namespace].checked_epoch,
        local_key(key),
        manager.keys.encode(manager[database][collection]._find_one_default_shape),
    )


def verify_published_payloads(
    observed: Mapping[NonNegativeInt, AbstractSet[bytes]],
    published: Mapping[NonNegativeInt, AbstractSet[bytes]],
) -> None:
    for key, values in observed.items():
        if not values <= published[key]:
            raise LookupError("a reader observed torn or unpublished bytes")


def raw_connection(config: AttachmentConfig, *, authenticate: bool) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect(config.socket_path)
    if authenticate:
        sock.sendall(encode_frame(config.hello()))
        _SyncConnection(sock).receive(
            time.monotonic() + 5, config.frame_limit, EndpointCounters()
        )
    return sock


def closed_peer(sock: socket.socket) -> bool:
    try:
        b"".join(iter(lambda: sock.recv(65_536), b""))
    except ConnectionResetError:  # pragma: lax no cover (peer reset timing)
        pass
    return True
