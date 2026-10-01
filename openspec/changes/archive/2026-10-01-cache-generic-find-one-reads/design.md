# Design

## Context

See [proposal.md](proposal.md) for motivation. The generic namespace mechanism already caches `find`, aggregation and counts, but `find_one` returns directly to PyMongo when `_match_unique_key` finds no eligible key. `tests/*/test_collection.py` explicitly asserts bypassing a compound predicate. The initial read design describes generic equality caching, and `cached-read-api` says an ineligible unique index uses a generic bounded read; implementation history (`517f19b2`, `448017a7`) instead consistently bypasses. This change resolves that conflict by implementing the broader specified fallback, not by claiming a regression.

The optimized identity shape currently includes projection and codec identity, and arbitrary keyword arguments trigger bypass. Collection options already preserve effective codec/read profiles. Generic query results must be invalidated for writes to any document because matching membership can change.

## Goals / Non-Goals

**Goals:** Reuse namespace guards for safe single-document reads, preserve optimized identity behavior, and provide explicit sort/collation support with correct cache separation.

**Non-Goals:** A query evaluator, stable ordering beyond MongoDB's own guarantees, additional driver option caching, cursor compatibility, cross-collection dependency tracking, or session/transaction caching.

## Decisions

### D1. Select identity, unique-key, or generic namespace paths

Normalize `None` and an empty filter to the same match-all generic query shape. Retain scalar-ID shorthand and exact `_id` equality on the identity path, including its existing uncanonicalizable-ID bypass. Deterministic mapping filters that are not exact identity reads can use unique-key matching when its existing unconditional-uniqueness rules are satisfied; otherwise use namespace lookup/admission. Never drop extra predicates merely because a filter contains `_id` or a unique field.

Apply the shared unsafe-filter and projection validation before the generic path. Unsafe or uncanonicalizable filter/discriminator values execute the original `find_one` call directly. Missing/inconclusive index metadata does not prevent generic namespace caching when collection type and stream continuity are independently confirmed. Preserve metadata logging and future reason accounting where a read actually bypasses.

The generic shape is `("find_one_generic", normalized_filter, read_shape, index_generation)`, encoded with the existing order-sensitive discriminator helpers. The read shape contains projection, ordered sort, effective collation and codec fingerprint. Include the current index generation so index changes re-evaluate the optimized path without per-hit discovery; select any qualifying unique path from current cached index metadata before taking a generic lookup, so optimized hits do not record a spurious generic miss. When metadata is unknown, check a warm generic entry before probing indexes, including after an inconclusive probe. Give it a distinct method tag so it cannot collide with `find` or unique-alias namespace entries. Lookup, capture the namespace generation before database I/O, execute one majority/primary `find_one`, then admit the document or `None`. Use the existing generation/availability race checks and BSON encode/decode isolation. No alias is created for an ordinary query result.

Alternative: call cached `find(..., limit=1)` and extract its first item. Rejected because it changes the operation/return envelope and unnecessarily allocates a list instead of preserving the driver's single-document call and its errors.

### D2. Declare sort and collation instead of guessing about arbitrary kwargs

Add keyword-only `sort: Sequence[tuple[str, int]] | None` and `collation: _CollationIn | None` to both `find_one` variants. Unknown kwargs remain a bypass. Forward the selected options unchanged to PyMongo on all direct paths; only cache-key construction normalizes collation.

The effective collation is the explicit collation when supplied, otherwise the confirmed collection default. Extend unique-key matching to receive that effective value. An index whose collation differs or whose equivalence cannot be proven locally routes to generic namespace caching, never to an unsound identity alias. Compare complete option documents after removing the server metadata version. Preserve inherited matching collations and fully specified explicit matches; short explicit collations with omitted defaults use generic caching conservatively. Do not fill omitted options from assumed universal defaults: [MongoDB documents locale-specific defaults](https://www.mongodb.com/docs/manual/reference/collation-locales-defaults/). Use the `_id` fast path only under confirmed simple/binary effective collation. Any non-simple effective collation, including an inherited collection default when the option is omitted, routes conservatively through the generic path because string matching can change which `_id` values qualify. Normalize scalar-ID shorthand to its `_id` predicate for that generic path. Deterministic regex-ID predicates also use generic namespace caching; they remain ineligible for exact-identity aliases. An explicit simple collation can retain the fast path even on a collection with a non-simple default. Do not infer an exact identity from a collation-sensitive query. The collection-default matching rule is documented in [MongoDB's collation guidance](https://www.mongodb.com/docs/manual/core/index-case-insensitive).

Include the ordered sort specification in identity and unique-key read shapes as well as generic discriminators. Even when uniqueness fixes the selected document, projection metadata can depend on sorting; retaining the sort avoids assuming that document identity alone fixes all projected output. Include effective collation in shapes wherever it can change matching or returned values, and keep projected and full-document shapes separate. Validate supported sort/projection combinations before taking any hit.

Alternative: whitelist options by reading arbitrary kwargs. Rejected because declared parameters provide editor discoverability and define the exact supported cache contract. Sorting does not promise deterministic tie-breaking that MongoDB itself does not promise.

### D3. Preserve errors and validate before taking a hit

Do not let caching mask malformed filter, projection, sort, or collation arguments. Reuse supported driver/public validation where available, or conservatively bypass invalid/unsupported shapes so PyMongo remains the error source. Equivalent valid options can share a normalized key only after validation; a malformed argument must not collide with a previously valid key. Do not duplicate MongoDB's query engine in client validation.

### D4. Share shape logic, retain native execution models

Use common pure normalization/discriminator logic where the variants would otherwise duplicate policy. Implement the database call and lifecycle/cancellation handling natively in each collection file. Reuse `CacheCore.lookup_namespace`, `capture_namespace_generation`, and `admit_namespace`; do not add another cache owner, namespace registry, or change stream. This change needs only the existing recording seam and has no hard dependency on diagnostics.

### D5. Resource costs and measurements

Reuse the immutable default read shape per facade and pass each canonicalized shape/discriminator through validation and lookup without normalizing it again. Generic hits perform O(Q) key normalization for query/option size Q and O(V) decode for result size V; misses add one `find_one` round trip and O(V) serialization. Unique-index discovery retains its existing per-index-generation cost, not a per-hit database request. A negative generic result consumes one bounded cache entry. Unrelated writes invalidate generic results conservatively; exact identity reads retain their narrower invalidation.

Profile compound-predicate and sorted/collated hits, misses, negative hits and write-heavy invalidation using an untracked harness alongside the existing hit regression workloads. Compare direct `find_one`, existing cached identity reads, and generic caching. Record reproduction commands, latency/allocations, hit rate, and the measured bottleneck in the implementation commit body. Planning claims no performance measurements.

## Risks / Trade-offs

- [A generic hit returns a document that no longer qualifies] -> Namespace guards cover membership and ordering; test mutations of matching and nonmatching documents, inserts after negatives, and reads spanning invalidation.
- [A collation changes identity matching] -> Use effective-collation matching for unique indexes and a generic path for all non-simple effective `_id` collations, including inherited defaults.
- [Option normalization hides a driver error] -> Validate before lookup or bypass; test malformed options after warming a valid entry.
- [Tests encode the narrower historical implementation] -> Replace the compound-predicate bypass expectation with behavior tests and retain genuine unsafe/profile/session bypass cases.
- [Shared cached-read spec changes collide with adapter work] -> The adapter study changes no runtime requirements; this delta owns generic `find_one` only.

## Migration Plan

The returned document/`None` contract stays unchanged. Safe reads previously bypassed now consume cache budget and observe the documented eventual invalidation model. Document current eligibility and explicit sort/collation support, including bypass choices for callers needing session semantics. Revert the generic path to direct execution if necessary; there is no persisted data migration.
