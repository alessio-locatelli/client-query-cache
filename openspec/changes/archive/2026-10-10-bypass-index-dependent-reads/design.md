# Design

## Context

See [proposal.md](proposal.md) for motivation and the [delta spec](specs/cached-read-api/spec.md) for the contract. `_core/read_validation.py` classifies reads with a recursive key denylist (`PIPELINE_UNSAFE_KEYS`, `FILTER_UNSAFE_KEYS`) and a system-variable denylist (`NONDETERMINISTIC_SYSTEM_VARIABLES`). Projection classification checks only `PROJECTION_UNSAFE_KEYS` (`$meta`) and no system variables. Both facades call it before lookup. A cacheable miss runs on a collection handle forced to majority read concern, and an unsafe classification sends the call to `.raw` with the caller's arguments. Index DDL events advance only the unique-key `index_generation`, not the namespace generation. No change event is consumed for search-index or role changes, and entries have no TTL.

Observed on 2026-10-10 with PyMongo 4.18.2 (scripts are not retained):

- On `mongodb/mongodb-atlas-local` 8.0.32 and 8.3.11, `$search`, `$searchMeta`, `$vectorSearch` and `$listSearchIndexes` succeed with unspecified or `local` read concern. With `majority` they fail with code 72 (`InvalidOptions`: the stage cannot run with a read concern other than `local`). Through a cached view with unspecified read concern, the first `$search` raises that error. Since admitted reads require majority, these stages can never be served from the cache, so the staleness in the audit cannot occur today; failing these reads is the actual defect.
- On `mongo:8.0.4-noble`, the integration-test image in `tests/conftest.py`, and on `mongo:9.0.2`, the contributor service in `docker-compose.yaml`, neither of which has `mongot`, the same stages fail with code 31082 (search not configured) with unspecified read concern, and with code 72 under majority. On 8.0.4, with the collection holding one document, the cached view raised 72 and `.raw` raised 31082, and the manager recorded no bypass, so the cached call reached the forced-majority miss.
- On Atlas Local 8.3.11, a cached `$geoNear` without `key` kept returning `[1, 2]` after `loc_2dsphere` was replaced by a 2dsphere index on another field. Native execution returned `[2, 1]`. A cached `$near` find kept returning documents after its index was dropped, while native execution failed with "unable to find index for $geoNear query". On `mongo:9.0.2`, hiding the only 2dsphere index through `collMod` made a native `$near` find fail with code 291.
- On Atlas Local 8.0.32 with authentication, a cached `$project` of `$$USER_ROLES.role` kept returning `["read"]` after `grantRolesToUser`. Native execution returned `["read", "readWrite"]`.
- On `mongo:8.0.4-noble` and `mongo:9.0.2`, `find_one` projections evaluate `$rand`, `$function`, `$$NOW`, `$$CLUSTER_TIME` and `$$USER_ROLES`, and reject `$sampleRate` and `$accumulator` with code 31325. On 9.0.2, repeated cached `find_one` and `find` calls with `$$NOW`, `$rand` or `$$USER_ROLES` projections returned identical results: six hits and no bypasses. On 8.0.4, `$geoNear`, `$near` `find_one`, `$nearSphere` `distinct` and a `$text` `$match` succeed with their index, and `count_documents` rejects `$near` with code 5626500.

MongoDB documents that search indexes are eventually consistent, and that `$geoNear` index selection and `spherical: false` distance geometry depend on which geospatial indexes exist: [self-managed search troubleshooting](https://www.mongodb.com/docs/search/self-managed/current/troubleshooting/), [`$geoNear`](https://www.mongodb.com/docs/manual/reference/operator/aggregation/geoNear/), [`$near`](https://www.mongodb.com/docs/manual/reference/operator/query/near/), [system variables](https://www.mongodb.com/docs/manual/reference/aggregation-variables/).

## Goals / Non-Goals

Use the existing classification boundary and bypass reasons. Leave `$rankFusion` and `$scoreFusion` without search inputs cacheable: their rankings derive from collection documents. Recursive scanning already reaches search stages nested in their input pipelines. Do not add `$$SEARCH_META` or the database-level metadata stages (`$currentOp`, `$listSessions`, `$querySettings` and others). `$$SEARCH_META` is valid only after a search stage. The other stages either cannot run through a collection-level aggregate or target internal databases where the database change stream cannot start, so the existing stream-unavailable bypass already applies.

## Decisions

### D1. Extend the denylists

Add `$search`, `$searchMeta`, `$vectorSearch`, `$listSearchIndexes` and `$geoNear` to the pipeline keys, and `$near` and `$nearSphere` to the filter keys. Rename `NONDETERMINISTIC_SYSTEM_VARIABLES` to `UNCACHEABLE_SYSTEM_VARIABLES` and add `$$USER_ROLES`, because role-dependent values are not nondeterministic. `$near` and `$nearSphere` stay out of the pipeline keys: MongoDB rejects them inside `$match`, and `$geoNear` covers pipeline proximity. Add `$rand` and `$function` to the projection keys and pass the variable set to projection classification, so `find_one` and `find` share one projection check. `$sampleRate` and `$accumulator` stay out of the projection keys because MongoDB rejects them there.

Alternative: replace the stage denylist with a fail-closed stage allowlist. Pros: a stage added in a later server release would bypass until reviewed. Cons: expression-level hazards (`$rand`, `$$NOW`, `$$USER_ROLES`) still require an expression or variable denylist. The change would also stop caching every valid stage the allowlist omits and would contradict the current enumerated-bypass contract. Unknowns: none that affect this defect. Conclusion: not adopted, and no follow-up is required for this change.

### D2. Execute search-backed stages natively

Classifying these stages as unsafe routes them to `.raw`, which keeps the caller's read concern, success or error, and native batching.

Alternative: admit them under `local` read concern. Pros: repeated searches would avoid `mongot`. Cons: local reads can be rolled back, and admission currently depends on majority. Indexing is asynchronous, so a miss after write invalidation can admit a pre-index result. With no TTL and no event when indexing finishes, that result stays stale until the next write. Search-index definition changes produce no consumed event. Unknowns: none; the observations above settle server behavior. Conclusion: rejected, and no research is necessary.

### D3. Bypass index-dependent reads instead of invalidating on index events

Alternative: advance the namespace generation on `createIndexes`/`dropIndexes`, and consume `modify` for hidden-index changes. This could make `$text` and proximity reads cacheable. Pros: retains caching for these reads. Cons: it needs a change-stream-coherency contract change and more stream traffic. Every index DDL would clear unrelated entries in the namespace. It would reverse the established `$text` bypass, and it still would not cover search indexes. Unknowns: whether every index-state transition that affects these operators emits a consumed event across topologies, for example aborted or rolling builds on sharded clusters. That would require a prototype. Conclusion: not adopted. The bypass matches the existing `$text` decision, and no follow-up is required.

### D4. Reuse `unsafe_pipeline`, `unsafe_filter` and `unsafe_projection`

A dedicated reason would add a public `BypassReason` member and metric label value. The existing monitoring definition, "a construct unsafe to cache", already covers these reads. Conclusion: no new reason, and no follow-up.

### D5. Keep the variable scan constant-time per string

Classification runs on every read, including warm hits. The scan tests each string node with one set lookup plus one `startswith` per variable, so a third variable adds a third prefix check. Precompute the dotted prefixes once per variable set and pass them to a single `str.startswith(tuple)` call. Keep the existing `TypeError` guard for unhashable string subclasses. Measure classification for a small filter, a multi-stage pipeline with string-heavy expressions, a large `$in` filter and a computed projection before and after the change. Record the results in the implementation commit body, as AGENTS.md requires.

### D6. Testing without `mongot`

Unit tests cover each new construct at top level and nested, including a search stage inside `$rankFusion`. Facade tests run against the existing `mongo:8.0.4-noble` integration replica set. A search-stage read on a collection holding a document must raise the same error code through the cached view as through `.raw` (31082), and the manager must record an `unsafe_pipeline` bypass for it. The document makes the collection exist, so the read cannot bypass as `missing_collection`, and the bypass assertion shows that classification, not stream or collection eligibility, sent it to `.raw`. The pre-change cached path raises 72. Proximity, `$$USER_ROLES` and variable-projection reads must reach the driver on every repetition. `$geoNear` and `$text` aggregations need a matching index and fixture document, so they get a separate parametrized test rather than joining the index-free unsafe-pipeline test. Projection cases use a plain filter, so the projection alone decides the bypass. Under the integration image's unauthenticated server, `$$USER_ROLES` evaluates to an empty array, which still exercises classification. Adding `mongot` or authentication to the test environment would need a second image and changes to test infrastructure without strengthening these assertions. Conclusion: not adopted, and no follow-up.

## Risks / Trade-offs

- [Applications lose caching for proximity, search, role-dependent and variable-projection reads] → Document each construct in the bypass reference. Those reads previously either failed or could become indefinitely stale.
- [Literal data spelling a new key, for example `{"$literal": {"$search": 1}}`, bypasses unnecessarily] → This is the accepted false-positive trade-off of the recursive scan: it costs a caching opportunity, not correctness.
- [A future server release adds another index- or environment-dependent construct] → Accepted with the enumerated contract (D1): such a construct needs its own change, as `$text` and this change did.
