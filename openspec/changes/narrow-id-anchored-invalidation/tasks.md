# Tasks

## 1. Research harness and baseline

- [ ] 1.1 Add `research/invalidation_scope/benchmark.py`, a standalone script with `# ruff: noqa: INP001` like `research/collection_adapter/live_error.py`. It implements design.md D3 for the workload, paths and topology listed under design.md Baseline evidence, with three `argparse` subcommands and a `signal.alarm(3600)` runtime bound.
  - **Seeding.** Document `i` gets `_id = i`, `author_id = i % 500`, `created = i` and `views = 0`. Create an index on `[("author_id", 1), ("created", -1)]`. Hot author `a` (0–31) owns document `_id = a`. The feed limit is 20.
  - **Writes.** An insert for author `a` gets an auto-generated `_id` and a `created` of 20,000 for the sequence's first insert, increasing by 1 per insert, so it becomes `a`'s newest document and enters `a`'s feed. An update applies `{"$inc": {"views": 1}}` to a uniformly drawn seeded `_id`. Draw each sequence from `random.Random(f"{mix}-{reads_per_write}-{rep}")`.
  - **`run --reps N --out PATH`.** Uses `IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="2g"))` and `build_client(BenchmarkClientTopologyConfig(tls_enabled=False, compressor=WireCompressor.NONE, discovery_enabled=False, shared_connections=False))`. It reseeds the target and the sibling collection for each cell. The `direct` path uses `with_options(read_preference=ReadPreference.PRIMARY, read_concern=ReadConcern("majority"))`. Path order reverses on odd repetitions, and `measure_controlled` wraps the measured loop. For each cell it writes reads/s, P50/P95/P99 per read class, process and container CPU, psutil RSS, and the manager hits, misses, bypasses, `used_bytes`, `entry_count`, stream invalidations and logical event bytes as deltas. On both cache paths, while the measured loop's `stream_cost_snapshot("bench").invalidations` delta is below its count of issued writes, the loop classifies each read from the `manager.snapshot()` hit delta and counts its hits per read class as pending-write hits. Once the delta catches up, sampling stops until the next write. Each cell reports hit shares gross and net of pending-write hits.
  - **`simulate`.** Replays the seeded sequences with synchronous invalidation. Under every policy, `by_id` is invalidated only by an update of its document. The policies differ as follows:
    - `current`: any write invalidates `feed`, `count` and `own`.
    - `id_anchor`: `own` behaves like `by_id`.
    - `insert_partition`: an insert invalidates `feed` and `count` only for its own author, and an update invalidates them for every author.
    - `field_dependency`: a `views` update leaves `count` valid.
    - `all`: the three rules above combined.
    - `exact`: `own` behaves like `by_id`. The policy tracks each hot author's 20 newest documents by `created`, including inserted ones. An insert for author `a` invalidates `feed` and `count` for `a`. An update invalidates `feed` for `a` only if its document is among `a`'s current 20 newest.

    It prints hit shares per mix, rate and read class.

  - **`micro --out PATH`.** Against a seeded collection with no writes, times 5 batches of 20,000 warm `find_one` hits for each of `{"_id": i}`, `{"_id": i, "author_id": a}` and `{"author_id": a}`, and reports the median µs per hit.

  Verify with `just lint`, then `PYTHONPATH="$PWD" uv run python research/invalidation_scope/benchmark.py simulate`: the `current` policy must report 25–27% overall and `id_anchor` 50–51%.

- [ ] 1.2 On the unchanged code, run `bash -c 'set -euo pipefail; source scripts/testcontainers-bridge.sh; PYTHONPATH="$PWD" uv run python research/invalidation_scope/benchmark.py run --reps 3 --out /tmp/agents/invalidation-scope/before-run.json; PYTHONPATH="$PWD" uv run python research/invalidation_scope/benchmark.py micro --out /tmp/agents/invalidation-scope/before-micro.json'`. Confirm that, net of pending-write hits, the `cache` path's `own` class stays below 5% hits and `by_id` stays above 95%. Keep the output untracked.

## 2. `_id`-anchored `find_one`

- [ ] 2.1 In `src/client_query_cache/_core/identity_reads.py`, replace `extract_id_identity` with `extract_id_anchor(filter_query)`, which returns `(identity, remainder)` per design.md D1. Non-anchored filters return `(NO_IDENTITY, {})`. A scalar shorthand or an exact `{"_id": v}` returns an empty remainder. A mapping containing `_id` returns the other top-level items in their original order. Rename `test_extract_id_identity` in `tests/core/test_identity_reads.py` to `test_extract_id_anchor`, and update its parametrization:
  - change `compound-filter` to expect `(1, {"extra": 2})`;
  - add `{"extra": 2, "_id": 1}`, which keeps the remainder order;
  - add `{"_id": {"$in": [1, 2]}, "a": 1}`, `{"_id": None, "a": 1}` and a regex `_id` with an extra key, each expecting `(NO_IDENTITY, {})`.

  Verify with `just pytest tests/core/test_identity_reads.py`.

- [ ] 2.2 Add an optional `remainder` argument to `find_one_read_shape` in `src/client_query_cache/_core/find_one_reads.py`, defaulting to empty. An empty remainder produces exactly the current shape, and a non-empty one appends it inside the existing `order_sensitive_discriminator_key` call. In `tests/core/test_find_one_reads.py`, add parametrized cases for each property: an empty remainder equals the omitted argument, a non-empty remainder differs, and remainders `{"a": 1}` and `{"a": 1.0}` differ. Verify with `just pytest tests/core`.
- [ ] 2.3 In `CachedCollection.find_one` in both `src/client_query_cache/synchronous/collection.py` and `src/client_query_cache/asynchronous/collection.py`, make the following changes:
  - use `extract_id_anchor`;
  - pass the remainder to every `find_one_read_shape` call, including the inherited-default-collation recomputation;
  - use `_find_one_default_shape` only when the remainder, projection, sort and explicit collation are all empty;
  - give `_find_one_by_id` a `filter_query` parameter and use it for its forced read and both direct fallbacks instead of `{"_id": identity}`.

  Leave the generic and unique-key branches unchanged. Verify that `git diff` between the two facades' `find_one` and `_find_one_by_id` differs only in `await`/async spelling.

- [ ] 2.4 In both facade test files, add integration tests:
  - `test_id_anchored_find_one_survives_writes_to_other_documents`, parametrized over inserting, updating, replacing and deleting another document through `independent_writer`. After `wait_for_stream_barrier`, the anchored read under `_spy_on_driver` makes no driver call and returns the cached document.
  - `test_id_anchored_find_one_refreshes_after_anchored_writes`, parametrized over five cases: an update that keeps the match; an update that breaks the extra predicate (expect `None`); a delete (`None`); an insert of the anchored `_id` after a cached `None` (expect the document); and an update that makes a cached `None` match. Each case makes exactly one driver call after the barrier and matches `collection.raw.find_one`.
  - `test_id_anchored_find_one_entries_are_separate`, which reads `{"_id": x}`, `{"_id": x, "owner": owner}` and `{"_id": x, "owner": other}` twice each and expects three driver calls, with each result matching `.raw`.

  Add an `anchored` case to `test_find_one_explicit_collation_changes_matching_without_alias_leaks` and to `test_find_one_inherited_collation_uses_namespace_invalidation`, using `{"_id": value, "rank": 1}`. Extend the `interrupted_generic_collection` fixture with a `write-other` parameter that updates a second, pre-inserted document. Add `test_id_anchored_find_one_admission_spanning_writes`, parametrized over `write` (expect a miss on the next read) and `write-other` (expect a hit), with the anchored query `{"_id": <fixture document id>, "rank": {"$gte": 1}}`. In `tests/synchronous/test_unique_key_reads.py` and `tests/asynchronous/test_unique_key_reads.py`, parametrize `test_cold_read_without_a_unique_key_match_records_one_miss` over its filter as well: `{"name": name}`, and the anchored `{"_id": document["_id"], "name": name}`. Verify with `just pytest tests/synchronous tests/asynchronous -k "anchored or collation or spanning or records_one_miss"`.

- [ ] 2.5 Update the user-facing descriptions of which reads keep their cached result after writes to other documents. Each description names three groups:
  - `find_one` reads that pin `_id` to an exact value under simple collation, alone or with additional predicates, and qualifying unique-index `find_one` reads, which can keep their cached result after writes to other documents;
  - other eligible `find_one` filters, which are refreshed after any write to the collection;
  - every `find`, `aggregate`, `count_documents`, `distinct` and `estimated_document_count` result, which is also refreshed after any write to the collection.

  Apply them in these places:
  - the invalidation paragraph of `docs/user/reference/api.md` § Single-document reads, keeping its unique-index qualification and collation sentences, with the example `cached_collection.find_one({"_id": order_id, "customer_id": customer_id})`;
  - the single-document paragraph of `docs/user/usage/cached-reads.md` § Filters, sorting, and collation;
  - the "Cache granularity" bullet of `docs/development/architecture.md`;
  - one new `context7.json` rule, as a hint to anchor owner- or tenant-filtered `find_one` lookups on `_id`. The rule must not present cached reads as suitable for authorization decisions, and the existing rule that sends authorization and other freshness-critical reads to PyMongo stays unchanged.

  Add a `### Features` entry under `## Unreleased` in `CHANGELOG.md`.

  Verify each statement against the facade code, then run `just lint`.

## 3. Evidence and follow-ups

- [ ] 3.1 Rerun the task 1.2 commands into `after-run.json` and `after-micro.json`, and rerun `simulate`. Confirm the following, using hit shares net of pending-write hits:
  - the `cache` path's `own` hit share matches its `by_id` share within 2 percentage points;
  - `feed` and `count` stay within 2 points of `before-run.json`;
  - the `micro` median for `{"author_id": a}` and `{"_id": i}` is no more than 5% slower than before. Investigate any larger slowdown before continuing.

  Put the before and after tables in the implementation commit body.

- [ ] 3.2 Run `gh issue create` twice:
  - "Evaluate stream-assisted invalidation for equality-filtered reads". It covers the insert-partition and update-field-name candidates from design.md D2, their modeled hit shares, the stream-contract change each requires, and the stream-cost measurement required before any design.
  - "Reduce cache-miss overhead for find reads". It carries the design.md Baseline evidence miss-cost figures and profile attribution.

  Verify that both URLs resolve with `gh issue view <number>`.

- [ ] 3.3 Write `docs/development/research/invalidation-scope.md`, covering the following:
  - the question;
  - the workload and topology;
  - the reproduction commands from tasks 1.2 and 3.1, using the `bash -c 'set -euo pipefail; source scripts/testcontainers-bridge.sh; …'` form of `docs/development/research/read-through-collection-adapter-evaluation.md`;
  - before and after results;
  - modeled policy hit shares;
  - which reads now survive unrelated writes, and which stay collection-wide;
  - the rejected and deferred candidates, linking the task 3.2 issues;
  - the limits: a single process, closed loop and local container, with multi-worker evidence in `benchmark-concurrent-worker-workload`.

  Link it from `docs/development/index.md`. In `docs/user/benchmarks/index.md` § Is caching a good fit, add a "Query shape" bullet. It says that `_id` and qualifying unique-index reads survive writes to other documents, that other cached reads in a frequently written collection mostly miss, and that each miss costs more than a direct read. It links the research report by its GitHub URL, as the guard-policy link does. Verify with `just lint` and `just docs-build`.

## 4. Code Quality

- [ ] 4.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization.
- [ ] 4.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies). OpenAI Codex is exempt from this rule because it understands the difference between garbage and valuable code comments.
