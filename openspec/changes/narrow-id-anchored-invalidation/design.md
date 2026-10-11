# Design

## Context

See [proposal.md](proposal.md#why) for motivation and the [delta specs](specs/) for the contracts.

Current mechanisms:

- **Identity guard.** An entry carries the namespace epoch and the generation of one document identity. `record_write` advances that generation from each insert, update, replace and delete event's `documentKey._id`. A clear, creation, drop or rename advances the epoch and reclaims the namespace.
- **Namespace guard.** An entry carries the namespace generation, which every write advances.
- **Unique-key aliases.** These map a unique-index value to an identity after a first resolution.
- **Stream projection.** It keeps routing fields only: no document contents, update descriptions or images.
- **`find_one` routing.** A filter whose only key is `_id`, or a scalar shorthand, uses the identity path under a simple effective collation. Every other deterministic filter uses unique-key matching or a generic namespace entry.
- **Other read methods.** `find`, `aggregate`, `count_documents`, `distinct` and `estimated_document_count` always use namespace guards.
- **Identity normalization.** Read identities pass through BSON encoding and stream-codec decoding before `order_sensitive_key`, so they have the same Python types as event identities.

### Baseline evidence

A single-process interleaved benchmark measured this baseline. It ran on a `mongo:8.0.4-noble` single-member replica set limited to 2 CPUs and 2 GiB, with PyMongo 4.18.2 and Python 3.14.7, and reused `benchmarks.stream_cost.topology.IsolatedReplicaSet` and `measurement.measure_controlled`.

- **Data.** 20,000 documents, 500 authors and a 512-byte body.
- **Reads.** The reads cycle over 32 hot authors and four read classes:
  - `feed`: `find({"author_id": a}).sort("created", -1).limit(20)`;
  - `count`: `count_documents({"author_id": a})`;
  - `own`: `find_one({"_id": id, "author_id": a})`;
  - `by_id`: `find_one({"_id": id})`.
- **Writes.** Each write either inserts a document for a uniformly drawn author as that author's newest document, which enters the author's feed, or applies `$inc views` to a uniformly drawn seeded document. Most writes are therefore unrelated to the hot keys.
- **Runs.** Each run measures 4,096 reads after a 512-read warm-up, with three repetitions in alternating path order.
- **Ideal bound.** A third path sends the same writes to a sibling collection in the same database. The stream then carries the same event load, but no cached entry is invalidated. This approximates perfectly precise invalidation.

Medians at one write per 100 reads, which were nearly identical for the insert and update mixes:

| Path                            | Reads/s      | Hit share | Client CPU/read | `mongod` CPU/read | P50 feed / count / own / by_id (ms) |
| ------------------------------- | ------------ | --------- | --------------- | ----------------- | ----------------------------------- |
| Direct PyMongo                  | 3,880–3,910  | n/a       | 0.10 ms         | 0.13 ms           | 0.19 / 0.26 / 0.18 / 0.12           |
| Cache, current invalidation     | 2,720–2,740  | 27%       | 0.22 ms         | 0.12 ms           | 0.50 / 0.40 / 0.28 / 0.04           |
| Cache, writes elsewhere (ideal) | 9,880–10,640 | 100%      | 0.07 ms         | 0.008 ms          | 0.11 / 0.06 / 0.04 / 0.03           |

At one write per 10 reads, write latency dominates: direct reads ran at 970–1,060 reads/s, the current cache at 1,030–1,050 and the ideal bound at 1,830–1,920.

- **Memory and stream.** Every path had about 106 MiB RSS, and the cache held 405 KiB. Each write produced one invalidation and about 357 logical stream bytes, on both the invalidating and the sibling path.
- **Hit share.** Only `by_id` hit. The three namespace-guarded classes stayed at 0–2%, because 128 distinct hot query keys exceed the reads between two writes.
- **Miss cost.** Under churn, the cache was slower than direct reads because a miss costs more than a direct read. A `feed` miss took 0.53 ms of wall time against 0.18 ms for the same direct read, and 0.39 ms of client CPU against 0.09 ms. A profile attributed a large share to canonicalizing the same find key four to five times per miss, plus per-document capture encoding.

The same operation sequences were replayed through a model in which each candidate policy invalidates synchronously. The model reproduced the measured current hit share:

| Policy                                | Insert mix | Update mix |
| ------------------------------------- | ---------- | ---------- |
| Current                               | 25–26%     | 25–26%     |
| `_id` anchoring (D1)                  | 50–51%     | 50–51%     |
| Insert-aware equality partitions (D2) | 74–75%     | 25–26%     |
| Update field-name dependencies (D2)   | 25–26%     | 50–51%     |
| All three                             | 99%        | 75%        |
| Exact (results actually changed)      | 99%        | ~100%      |

## Goals / Non-Goals

**Goals:**

- Narrow invalidation only where the existing identity guard already proves which writes can affect an entry.
- Leave reproducible evidence and tracked follow-ups for the broader problem.

**Non-Goals:**

- Predicate-, partition- or dependency-aware invalidation.
- Any change to the stream pipeline, the projection or the routing.
- Pre- or post-images, and TTLs.
- Optimizing the miss path.
- Multi-worker evidence, which belongs to `benchmark-concurrent-worker-workload`.

## Decisions

### D1. Route `_id`-anchored `find_one` filters to the identity guard

A mapping filter is anchored when it has a top-level `_id` key whose value passes the existing equality extraction, which rejects null, regex and `$`-operator values. The remaining predicates form the remainder, in their original order. The extraction helper in `_core/identity_reads.py` returns the identity together with that remainder, and an exact-`_id` or scalar-shorthand read has an empty remainder.

For a non-empty remainder, the identity read shape appends the remainder. The read shape already carries projection, ordered sort, explicit or effective collation and the codec fingerprint, and `find_one_read_shape` builds the extended shape with the existing discriminator key. An empty remainder keeps today's exact shape, so plain `_id` reads and resolved unique-key aliases keep sharing entries. `_find_one_by_id` executes the normalized original filter instead of rebuilding `{"_id": identity}`, so it sends the remainder to the server; for an exact `_id` read the two filters are equal. The unique-key and generic paths are unchanged. An anchored filter with a non-simple effective collation still takes the generic path, as `{"_id": value}` does today.

**Correctness.** With simple collation, the implicit conjunction restricts the result to documents whose `_id` equals the identity under MongoDB comparison. Sort and projection apply only to those documents. Usually there is at most one; there can be more only in a sharded collection whose shard key excludes `_id`. How each event can affect the entry:

- **Insert, update, replace and delete.** Each affects that set only when its document's `_id` equals the identity. The event then carries that `_id` in `documentKey`, and `record_write` advances the identity generation. Identity routing follows MongoDB numeric equality, as the `cache-core` requirement "Identity matching follows MongoDB numeric equality" specifies.
- **Membership.** `_id` is immutable, so an update cannot move a document into or out of the set.
- **Inserts after a negative result.** Missing results become stale only through an insert of that `_id`, which is routed.
- **Capped and TTL deletions.** In probes against the same server, a capped collection's eviction and a TTL deletion each emitted a `delete` event.
- **Clear, creation, drop, rename and database invalidation.** These advance the epoch or mark the stream unavailable, as they do today.
- **Index changes.** Index events do not advance namespace generations today either, so anchoring adds no index exposure. Hints bypass caching. Index-dependent operators, `$text` and the proximity operators, bypass caching too.
- **Pagination.** `find_one` has no cached skip or limit.
- **Concurrent admission.** `begin_identity_admission` captures the identity generation before the database read. A write to the identity that is processed before admission rejects it, while writes to other documents do not touch that generation.
- **Stream interruption and recovery.** The availability generation and the namespace clear on lost history apply unchanged.

Alternatives:

| Alternative                                                    | Pros                                         | Cons                                                                                                                                                                             |
| -------------------------------------------------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Keep namespace guards for anchored filters (status quo)        | No code                                      | Owner-filtered reads are invalidated by every unrelated write                                                                                                                    |
| Also anchor `count_documents`, `distinct`, `find`, `aggregate` | Same correctness argument                    | `find`/`aggregate` need identity-guarded cursor capture and find-family compatibility metadata; anchored counts and distincts are uncommon; each doubles sync/async test surface |
| Treat `{"_id": {"$eq": v}}` as anchored                        | Covers ODM-generated equality                | Operator interpretation in classification for an unobserved spelling                                                                                                             |
| Execute `{"_id": identity}` and filter the remainder locally   | Shares one cached document across remainders | Requires a client-side query evaluator, which the request excludes                                                                                                               |

Unknowns: none that a prototype must settle. Conclusion: adopt D1 for `find_one` only. The alternatives need no follow-up unless usage evidence appears.

### D2. Keep collection-wide invalidation for all other reads

| Candidate                                                         | Pros                                                                                                     | Cons                                                                                                                                                                                                                                                                                                                                                                      | Unknowns                                                                                                                                                 |
| ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Insert-aware equality partitions using inserted document contents | Fixes the motivating example: modeled feed and count hit share rises from 0–2% to 98% under insert churn | The stream must carry inserted contents for every collection in the database, contradicting the projection requirement; needs a new reference-counted partition guard and find-family integration; needs Python alignment with MongoDB equality for arrays, numeric types, null or missing values and collation; updates, replacements and deletions stay collection-wide | `mongod` CPU and stream bytes of projecting inserted documents, or bounded top-level scalars with an unknown-value marker, across the stream-cost matrix |
| Update field-name dependencies using `updateDescription` names    | Small events; modeled counts survive unrelated updates (0% to 100%)                                      | Full-document finds still invalidate on every update (feed stays at 2%); needs conservative field-path extraction from filters, sorts, projections and pipelines; changes the stream projection                                                                                                                                                                           | Server cost of computing names; how many real workloads use projected or count reads                                                                     |
| Track the IDs in each cached result                               | No stream change for deletions                                                                           | Insufficient alone: inserts, membership-changing updates, limit and skip windows, negative results, counts and aggregations; sound only together with field names, for unlimited or zero-skip finds; per-entry ID sets cost memory                                                                                                                                        | None decisive                                                                                                                                            |
| Pre- and post-images, or `fullDocument: "updateLookup"`           | Old and new values for every write                                                                       | Per-collection DDL, image storage and extra server writes, excluded by default; a lookup returns the state at lookup time, so routing can target the wrong partition; adds a lookup per event                                                                                                                                                                             | None decisive                                                                                                                                            |
| Finite `_id` sets (`$in`) with multi-identity guards              | Batch loads would survive unrelated writes                                                               | Variable-length guards, N reference counts, O(N) validation per hit, and cursor-path integration, because `$in` reads mostly use `find`; no measured workload                                                                                                                                                                                                             | Demand                                                                                                                                                   |
| TTL-bounded entries                                               | Simple                                                                                                   | Not invalidation; excluded by the request                                                                                                                                                                                                                                                                                                                                 | None                                                                                                                                                     |

Conclusion: implement none of these in this change. The two stream-assisted candidates have the largest modeled benefit, but each changes the stream contract and adds a guard subsystem whose stream cost has not been measured. Task 3.2 opens a follow-up issue that requires that measurement before any design. The other candidates need no follow-up.

### D3. Evidence harness

`research/invalidation_scope/benchmark.py` is a standalone research script, following `research/collection_adapter/live_error.py`. It runs the workload and paths from the baseline evidence above, and its `simulate` subcommand replays the same seeded sequences through the policy model. It reuses `IsolatedReplicaSet` and `measure_controlled`, and records psutil RSS and manager snapshot and stream-cost deltas.

The model invalidates synchronously, whereas the stream applies a write after it returns, so a measured hit can come from an entry that a pending write is about to invalidate. The harness counts these pending-write hits separately, and comparisons with the model use hit shares net of them. A stream barrier after every write would remove them, but it would distort throughput. The baseline above does not separate them. The report lives in `docs/development/research/invalidation-scope.md`. Raw output stays untracked.

| Alternative                                   | Pros                                   | Cons                                                                                                                 |
| --------------------------------------------- | -------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Standalone research script (chosen)           | Small; reuses topology and measurement | Single process, closed loop, local container                                                                         |
| Extend `benchmarks/stream_cost/shared_cache/` | Open loop, multi-worker                | `benchmark-concurrent-worker-workload` is generalizing that harness now; multi-process adds nothing to this question |
| Stream-cost run matrix                        | Established reports                    | Separate read and write phases cannot show interleaved invalidation                                                  |
| Performance regression guard                  | Runs on every pull request             | Covers hot paths only, not hit rate under churn                                                                      |

Unknowns: none for this decision. Conclusion: adopt the standalone script. No follow-up is needed.

### D4. Defer the miss overhead

The miss overhead is a separate, pre-existing cost that remains for every non-anchored read under churn. Repeated canonicalization of one find shape and per-document capture encoding dominate it. This change does not touch the miss path, so task 3.2 opens a second issue with the profile evidence.

## Risks / Trade-offs

- [A hot document's writes invalidate every anchored remainder cached for it] → This matches projections and sorts today, and the LRU budget bounds the entries.
- [Anchor extraction runs on every eligible `find_one`] → A filter without `_id` pays one membership test. Tasks 1.2 and 3.1 measure hit cost before and after.
- [Single-process local evidence can misstate production behaviour] → The research report states its topology and limits, and the multi-worker evidence stays in the concurrent-worker change.
- [Users may expect every read to survive unrelated writes] → The guides state which reads use per-document invalidation and which stay collection-wide.

## Migration Plan

The public API does not change. Anchored reads become hits after unrelated writes. Rollback reverts the commits; no persisted state exists.
