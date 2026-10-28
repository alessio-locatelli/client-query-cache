from __future__ import annotations

from typing import TYPE_CHECKING

from client_query_cache._core.entries import AdmissionOutcome

if TYPE_CHECKING:
    from client_query_cache import CacheCore
    from client_query_cache._core.keys import NamespaceId


def evict_identity_preserving_namespace(
    cache: CacheCore,
    namespace: NamespaceId,
    identity: object,
    discriminator: object,
    read_shape: object,
) -> None:
    assert cache.lookup_identity(namespace, identity, read_shape).hit
    encoded = cache.lookup_namespace_encoded(namespace, discriminator)
    assert isinstance(encoded, bytes)
    before = cache.snapshot()
    assert before.entry_count == 2
    assert before.used_bytes == 2 * len(encoded)

    # Admit equal-sized entries until exactly one entry exceeds the budget.
    # The namespace lookup above makes the identity the least recently used.
    filler_count = before.shared_budget_bytes // len(encoded) - 1
    capture = cache.capture_namespace_generation(namespace)
    for index in range(filler_count):
        assert (
            cache.admit_namespace_encoded(capture, ("filler", index), encoded)
            is AdmissionOutcome.ADMITTED
        )

    assert cache.snapshot().evictions == before.evictions + 1
    assert not cache.lookup_identity(namespace, identity, read_shape).hit
    assert cache.lookup_namespace_encoded(namespace, discriminator) == encoded
