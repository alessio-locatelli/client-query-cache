# Design

## Context

See [proposal.md](proposal.md) for motivation and [the cache-core delta](specs/cache-core/spec.md) for the contract. The current baseline is `d74e67041c26718ec32c8e44d61e811ac5096700`. Its compact-key implementation returns canonical tagged nodes by identity, but `query_bypass_reason()` and `pipeline_bypass_reason()` discard their canonicalization result. The generic `find_one()` path already retains canonical inputs. Core lookup and admission accept both raw and canonical keys.

The existing `cached-read-api` requirements already cover uncanonicalizable fallback, native validation, lazy find construction, complete-consumption admission, and compatible limits. The main `cache-core` spec already covers key equality, generation guards, and outcome accounting. This delta adds a CPU-work bound and makes the affected precedence explicit; it does not replace those contracts.

## Goals / Non-Goals

The method boundary is the four methods named in the delta. `estimated_document_count()` uses the fixed discriminator `("estimated_document_count",)` with no caller-controlled key values, so it remains outside this change. Generic `find_one()` is the reference path and retains its existing behavior; identity and alias canonicalization, write routing, per-document encoding, and one-pass fusion of the order-sensitive builder with canonicalization are also outside this change.

## Decisions

### 1. Shared preparation returns a key or a bypass reason

In `_core/read_classification.py`, replace the two discriminator-checking helpers with `prepare_query_key(filter, projection, raw_key)` and `prepare_pipeline_key(pipeline, raw_key)`. Each returns a pair containing a canonical key or a bypass reason; a successful key can itself be `None`, so callers branch on the reason. Both use one private canonicalization helper that catches only `UnsupportedCacheRequestError`. The query helper checks filter safety before projection safety; the pipeline helper checks pipeline safety. Neither canonicalizes unsafe input. They do not record statistics.

Facade request classification and native argument preparation remain before these helpers. Collection eligibility remains after successful preparation. Call sites must use explicit control flow instead of an eager helper argument inside an `or` chain. Count and distinct retain the prepared discriminator for lookup and admission; aggregation retains it in `CursorCapture`. The sync and asyncio facades use the same helpers. No cache or global memoization is introduced.

| Alternative                                                   | Advantages                                                                             | Costs and unknowns                                                                                            | Disposition                                                                                             |
| ------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Shared key/reason preparation, selected                       | One exception boundary and safety order for both facades; no new per-read result class | Allocates a small return tuple; net CPU effect needs measurement                                              | [Task 3.1](tasks.md#3-performance-evidence) measures it; no separate research needed                    |
| Separate classification and inline try/except at every caller | Straight-line local code                                                               | Duplicates failure handling across methods and execution models; no unresolved technical unknown              | Rejected; no research needed                                                                            |
| Builder emits canonical nodes directly                        | Could remove the remaining builder-to-canonical pass                                   | Changes when errors arise at every builder caller, including write routing; incremental benefit is unmeasured | Outside this work's acceptance boundary; no builder prototype is needed to resolve repeated preparation |

### 2. Find carries a canonical family through its existing shape

Find preparation calls `prepare_query_key()` with the final native filter/projection and `shape.family`. On success it creates a `FindReadShape` with that canonical family and the final limit, and builds the admission discriminator with `find_discriminator()`. It supplies the prepared shape to `lookup_find()` and derives `FindSource` from that same shape. This retains the existing core interfaces and their support for raw callers.

The core can still call `canonicalize()` on a canonical family: its constant-time identity return is allowed by the delta. Exact and candidate discriminators can have separate constant-size wrappers around that family. The bound counts raw-tree canonicalization, not recursive function invocations or wrapper creation. Native `_spec`, pipeline, and options are never replaced with key representations. Prepared shapes stay local to `_prepare()`; rewind and clone prepare again through their existing lifecycle.

Adding a second discriminator parameter to core find lookup could share the exact wrapper too, but would create two representations of the same request that callers must keep consistent. A new prepared-find class would add a second shape abstraction. Neither is needed to avoid raw-tree rebuilding; there are no unresolved correctness questions or research tasks for these alternatives.

### 3. Measure traversal work separately from end-to-end hits

Let N be the discriminator tree size and R the returned BSON size. The selected path is:

| Step                                            | CPU and allocations                                                                                | I/O                                                     |
| ----------------------------------------------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| Build order-sensitive representation            | O(N), one temporary tree                                                                           | None                                                    |
| Safety classification and canonical preparation | Safety checks inspect relevant input; canonicalization walks N once and creates one canonical tree | None                                                    |
| Lookup and find source metadata                 | Canonical passthrough and constant-size wrappers; tuple hashing/equality can still inspect N       | Existing metadata/stream establishment only when needed |
| Hit delivery                                    | O(R) decode and existing cursor bookkeeping                                                        | No result query                                         |
| Miss capture and admission                      | Existing O(R) encoding; key preparation reuses canonical nodes                                     | Existing native result query and batches                |

The optimization reduces a constant multiplier on key preparation. It does not make query hashing constant-time, remove BSON decoding, or eliminate the independent order-sensitive builder pass. Per-cursor capture retains the prepared tree until completion/abandonment; there is no key registry or memory growth across completed requests.

[Task 3.1](tasks.md#3-performance-evidence) owns the measurement protocol and report. No percentage improvement is assumed in advance. Acceptance needs lower per-hit CPU for both find and aggregation, with native command counts unchanged; a noisy or non-improving result requires investigation before claiming the issue resolved. Small-result workloads expose key costs; decoding may dominate large results.

## Risks / Trade-offs

- Moving preparation ahead of an earlier condition could change public bypass counts or native errors. The delta's precedence scenarios and existing observability tests constrain this.
- Find exact keys, admission keys, and compatibility families could diverge. Equality checks against the baseline representation and tests spanning exact hits, covering hits, and admissions guard this boundary.
- Tests that count every `canonicalize()` call would reject valid constant-time passthrough. [Task 2.2](tasks.md#2-cursor-preparation-and-regression-coverage) specifies instrumentation of raw roots, including the module-global call used by `is_canonicalizable()`, and the sensitivity check.
- The active `narrow-id-anchored-invalidation` plan also names miss-path canonicalization as measured overhead. It changes `find_one()` routing, outside this method boundary; do not rewrite or implement that plan here.

## Migration Plan

No persisted keys or public signatures change. Update `docs/development/architecture.md` to describe prepared-key ownership. Public guides and `context7.json` retain their current contracts because this is an internal CPU optimization. Reverting the implementation restores repeated work without a data migration.
