## Context

See proposal.md for motivation. The corrected owner is preserved at `de8408aa3cde0ba2c674c253458975eacac84d81`; the original measurements and decision remain in `reports/native-process-local-cache/results.md`. Historical registration is not rewritten to imply different preregistered rules.

## Decisions

### Adopt the corrected owner in the existing extension

Compile its safe Rust local owner with the ordinary Python extension feature and export the class directly. Both managers and the public process-local core constructor use it. Structural protocols describe shared read/coherence operations; the observer-capable Python owner remains private to shared-cache coordination. Original Python canonical keys and BSON bytes remain owned Python objects, preserving numeric distinctions, codecs, callbacks, and key equality. No backend selector, prototype feature, or fallback is shipped.

This reuses measured ownership and the existing packaging/toolchain. A Python compatibility facade would preserve concrete types but add indirection and maintain an unused abstraction; the user explicitly prefers a clean implementation over compatibility with nonexistent users. Replacing the shared owner as well would require additional publication/observer machinery without demonstrated benefit. Neither alternative needs further investigation in this change.

### Ownership and costs

A single mutex protects native indexes, generation state, global weighted LRU, and find-family source indexes. Python equality, codecs, and reference destruction run outside it with mutation-version revalidation. GC traversal exposes strong edges, including captures that outlive close.

| Path               | Work and resources                                                                                                                        |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Exact hit          | Hash/key comparison, expected constant-time bucket and LRU work; BSON decode proportional to returned bytes; no database or network call. |
| Admission          | Encode once, expected constant-time indexing plus reclaimed entries; BSON budget and metadata scale with resident entries.                |
| Compatible find    | Ordered source index within one family; owned payload is reused, not duplicated.                                                          |
| Invalidation/close | Work scales with the affected namespace/resident storage; owned references drop outside the mutex.                                        |

The original candidate reduced CPU across all five corrected target blocks. The user accepted the reported ordinary-close allocator retention (including the synchronous long-key median cost around 8 MiB) and small document-residency memory increases as nonmaterial for this decision. This does not approve new regressions. Full results and limitations stay in the report, with no claim of universally faster operations or an RSS bound.

### Final integration acquisition

Before timing the integrated wheel, freeze its revision and build an ordinary release wheel without experimental features. Compare it with frozen main `1f70de76b6bc9fdcc4ab7cf0d4a8a4d784d9588e` using the same dependencies and host. Use three counterbalanced matched blocks, extending once to five when a result is uncertain. Never discard a valid unfavorable block or choose another winning metric after acquisition. Consistent paired direction and variation must support the observed gain; uncertain small effects remain inconclusive, regardless of their median.

Reuse the existing five-shape public harness for sync/async hot/cold direct and independent-worker controls, equal-residency memory lifecycle controls, and single-core invalidation contention. Measure ordinary shared warm reads and fresh import/startup wall/CPU, RSS and worker-plus-owner PSS. Keep expected outcomes, actual implementation, installed paths, residency, and source identities with raw untracked measurements. Existing corrected conformance and measurements remain evidence; final-wheel controls establish whether normal integration changes their applicability. Compare frozen existing tests separately from new owner tests, using equivalent invocation and environment. Record final results and reproduction commands in the existing report.

The remaining unknown is final ordinary-wheel integration cost, addressed by task 3.1; no new architectural choice depends on it. A new material cost blocks completion until corrected or discussed. Reverting this integration commit restores the prior implementation without a data migration: storage is process-local and ephemeral.
