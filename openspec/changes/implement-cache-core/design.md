## Context

The prototype contains unbounded cache types. The retained architecture requires a shared manager budget, immutable value storage, and admission guards before facades or streams are introduced.

## Goals / Non-Goals

**Goals:** Establish manager state, canonical identity, BSON-weighted LRU storage, and safe inspection.

**Non-Goals:** This change does not watch MongoDB or expose public cached reads.

## Decisions

- Use one manager-owned weighted BSON LRU with a 64 MiB default and a 1 MiB maximum entry, both configurable.
- Represent document and derived-result identities separately. Namespace generation guards prevent an older in-flight read from being admitted after invalidation.
- Encode on admission and decode on return to isolate caller values and measure resident size consistently.
- Make lifecycle and measurement snapshots immutable and safe for logs.

## Risks / Trade-offs

- [BSON serialization adds CPU] → It buys mutation isolation and accurate weighted capacity; benchmarks evaluate the cost later.
- [In-flight reads race with invalidation] → Check generation before and after database reads.

## Migration Plan

Replace prototype storage with driver-neutral primitives, cover them with pure unit tests, then expose them only through later facade work.
