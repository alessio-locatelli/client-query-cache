# Process memory beyond the BSON budget

These measurements support capacity planning and diagnosis of retained memory.
They are dated observations, not memory bounds for the current release.
Configuration and ownership rules belong in the [API reference](../../docs/user/reference/api.md#optional-retention-limits)
and [architecture guide](../../docs/development/architecture.md).

## Native-core residency

The ordinary-wheel adoption campaign compared the Python core at
`1f70de76b6bc9fdcc4ab7cf0d4a8a4d784d9588e` with the native core at
`cd9967d0592edc06568748c081926a3136b1c6fd`, using harness
`34cb5fa4187a9c7ad22ea6aab1a99d02ec16278c`. Five paired blocks alternated
M/F and F/M. Both APIs used CPython 3.14.7, PyMongo 4.18.2, psutil 7.2.2,
an Intel Core i3-13100, Linux/Fedora Toolbx and glibc 2.43. MongoDB was the
pinned `mongo:9.0.4` single-member replica set. Fresh measured processes ran
separately from MongoDB; server memory is excluded.

The native column below is baseline-adjusted cached-minus-direct warm PSS,
with limits disabled. Short/long-filter cells held 64,001 entries and 3,776,008
BSON bytes in both implementations. Documents held 14,001 entries. Values are
medians of five blocks; sync/async results agree within 0.1 MiB.

| Shape                                              | Native warm growth, MiB | Native PSS bytes/entry | Python-core growth, MiB |
| -------------------------------------------------- | ----------------------: | ---------------------: | ----------------------: |
| 4.4 KB documents by `_id`                          |                    66.6 |                  4,990 |                    66.2 |
| 59-byte results, one-field filter                  |                    37.7 |                    617 |                    44.8 |
| 59-byte results, per-request 48-value `$in` filter |                   261.8 |                  4,289 |                   268.9 |

The long-filter cell retained about 73 times its charged BSON in process memory.
Moving metadata into Rust did not remove the Python filter objects retained by
canonical keys. At equal residency, the later native-internals campaign
(`c931b679` to final `ed92c9c2`) measured 38.18 MiB for short filters and
262.39 MiB for long filters, versus 67.08 MiB for the document cell. That campaign
also found that embedding a shared-arena descriptor in every local entry added
about 29 bytes per entry; keeping arena blocks in shared-owner residency removed
that cost. See [native migration evidence](../native-internals/results.md).

Normal close and explicit diagnostic trimming differ. Native document processes
ended near 104–105 MiB absolute PSS, while Python-core processes ranged about
43–109 MiB; both returned to about 41–43 MiB after glibc `malloc_trim(0)`.
Synchronous long-filter close differences had mixed signs (−0.81 to +5.86 MiB,
median +2.71 MiB). Five fill/close cycles plateaued: native fifth-close medians
were 46.98/46.81 MiB sync/async, versus 48.04/48.19 MiB for the Python core.
These observations support allocator retention as a diagnostic alternative to
a leak, but do not prove that every later memory-growth symptom is harmless.
The library does not trim the allocator.

## Cursor capture and allocator retention

An October 10–11 campaign on the Python core measured 32 open cursors, each
consuming 220 of 224 catalogue documents. They retained 29.3 MiB of encoded
candidate payload and added 34.1 MiB RSS sync (33.8–34.2) or 30.6 MiB async
(30.1–33.2) above direct reads. Closing left 18.6/30.0 MiB; diagnostic trimming
reduced both to about 4.7 MiB. Five fresh-process repetitions used CPython
3.14.7, PyMongo 4.18.2, MongoDB 8.0.4, a Ryzen 3 210 and glibc 2.39 in
Ubuntu 24.04 containers. This is historical scale evidence; capture now uses a
native encoded accumulator, so these wrapper costs are not a current estimate.

The ongoing capture ownership and allocation boundaries are documented in
[the architecture guide](../../docs/development/architecture.md#low-level-design).
Measure simultaneous partial cursors separately from stored cache bytes and
application-held results. RSS after release measures allocator residency as
well as live objects; inspect ownership and repeated-cycle growth before
classifying a leak.

## Retention safeguards qualification on 2026-11-03

Baseline `4e071dfd5904527545177cd2e6f5bdb78a2239c9` and candidate
`94065fbff5439c47268bd38e85b2101c95f9f30f` used independent release PGO wheels.
The host was an i3-13100, CPython 3.14.7, PyMongo 4.19.0, psutil 7.2.2,
Linux 7.2.15, glibc 2.43, Rust 1.99.1 and Maturin 1.16.0. MongoDB was
`mongo:9.0.4@sha256:dc28ed5a9d0fc616903c3f463bb1e53b92b49f441721b91926e87d90bf957ce8`.
These measurements use the native core, before telemetry became opt-in.

### Memory protection on the issue #337 workload

The scenarios read 100,000 seeded documents (`{"_id": i, "code": "C%07d", "state": "active"}`, `code` indexed) through a cached `find_one` view in three phases: 64,000 distinct reads (cold), the same 64,000 again (warm) and 36,000 further distinct reads (evict). The BSON budget is 4 MiB, which holds 71,089 of the 59-byte results. The four scenarios cross the filter with the access order:

| Scenario         | Filter                                                            | Access order                                                  |
| ---------------- | ----------------------------------------------------------------- | ------------------------------------------------------------- |
| `small-entries`  | `{"code": ...}`                                                   | Sequential, each key once per phase                           |
| `large-keys`     | `{"code": ..., "state": {"$in": [48 values]}}`, built per request | Sequential                                                    |
| `skewed-entries` | `{"code": ...}`                                                   | 164,000 reads at log-uniformly distributed indexes (seed 337) |
| `skewed-keys`    | The 48-value filter                                               | The same skewed reads                                         |

The configurations are a plain PyMongo process (`direct`, the reference for Δ RSS), the frozen baseline, the candidate with limits disabled, `max_entries=10000` (count), `max_key_bytes=2048` (key), both, and the deployment guide's example (`example`), `max_entries=50000` with `max_key_bytes=16384`. Δ RSS is the cached process's RSS minus the direct process's at the end of the last phase; the table gives the median and range of three repetitions of the synchronous API, and the asynchronous API agrees within 0.5 MiB with identical counts. The phase peak equals the end value in every row. "Warm hit rate" is the share of the 64,000 warm reads served from the cache.

`large-keys` reproduces the issue: 71,089 small results behind long filters hold 297 MiB of RSS above the plain driver, although only 4 MiB of BSON.

| Configuration | Δ RSS at end / peak, MiB    | Values + aliases | Charged BSON | Warm hit rate % | Origin queries: cold / warm / evict | Declines   |
| ------------- | --------------------------- | ---------------- | ------------ | --------------: | ----------------------------------- | ---------- |
| baseline      | 296.5 / 296.5 (296.5–296.6) | 71089 + 0        | 4194251 B    |           100.0 | 64000 / 0 / 36000                   | 0 / 0      |
| disabled      | 296.7 / 296.7 (296.7–296.9) | 71089 + 0        | 4194251 B    |           100.0 | 64000 / 0 / 36000                   | 0 / 0      |
| example       | 211.6 / 211.6 (211.6–211.7) | 50000 + 0        | 2950000 B    |             0.0 | 64000 / 64000 / 36000               | 0 / 0      |
| count         | 46.5 / 46.5 (46.4–46.5)     | 10000 + 0        | 590000 B     |             0.0 | 64000 / 64000 / 36000               | 0 / 0      |
| key           | 4.8 / 4.8 (4.6–4.8)         | 0 + 0            | 0 B          |             0.0 | 64000 / 64000 / 36000               | 164000 / 0 |
| both          | 4.7 / 4.7 (4.6–4.8)         | 0 + 0            | 0 B          |             0.0 | 64000 / 64000 / 36000               | 164000 / 0 |

`skewed-keys` is the same filter under a skewed access pattern:

| Configuration | Δ RSS at end / peak, MiB    | Values + aliases | Charged BSON | Warm hit rate % | Origin queries: cold / warm / evict | Declines   |
| ------------- | --------------------------- | ---------------- | ------------ | --------------: | ----------------------------------- | ---------- |
| baseline      | 146.5 / 146.5 (146.4–146.8) | 34746 + 0        | 2050014 B    |            82.5 | 18594 / 11177 / 4975                | 0 / 0      |
| disabled      | 146.9 / 146.9 (146.8–147.0) | 34746 + 0        | 2050014 B    |            82.5 | 18594 / 11177 / 4975                | 0 / 0      |
| example       | 146.9 / 146.9 (146.8–147.0) | 34746 + 0        | 2050014 B    |            82.5 | 18594 / 11177 / 4975                | 0 / 0      |
| count         | 46.1 / 46.1 (45.9–46.2)     | 10000 + 0        | 590000 B     |            72.2 | 20109 / 17771 / 9842                | 0 / 0      |
| key           | 4.7 / 4.7 (4.5–4.8)         | 0 + 0            | 0 B          |             0.0 | 64000 / 64000 / 36000               | 164000 / 0 |
| both          | 4.8 / 4.8 (4.5–4.8)         | 0 + 0            | 0 B          |             0.0 | 64000 / 64000 / 36000               | 164000 / 0 |

`skewed-entries` and `small-entries` use short filters, whose keys are small; the limits then trade hit rate for memory only through the entry count.

`skewed-entries`:

| Configuration | Δ RSS at end / peak, MiB | Values + aliases | Charged BSON | Warm hit rate % | Origin queries: cold / warm / evict | Declines |
| ------------- | ------------------------ | ---------------- | ------------ | --------------: | ----------------------------------- | -------- |
| baseline      | 24.5 / 24.5 (24.4–24.6)  | 34746 + 0        | 2050014 B    |            82.5 | 18594 / 11177 / 4975                | 0 / 0    |
| disabled      | 24.7 / 24.7 (24.7–24.8)  | 34746 + 0        | 2050014 B    |            82.5 | 18594 / 11177 / 4975                | 0 / 0    |
| example       | 24.8 / 24.8 (24.6–24.8)  | 34746 + 0        | 2050014 B    |            82.5 | 18594 / 11177 / 4975                | 0 / 0    |
| count         | 10.6 / 10.6 (10.5–10.6)  | 10000 + 0        | 590000 B     |            72.2 | 20109 / 17771 / 9842                | 0 / 0    |
| key           | 24.9 / 24.9 (24.7–24.9)  | 34746 + 0        | 2050014 B    |            82.5 | 18594 / 11177 / 4975                | 0 / 0    |
| both          | 10.5 / 10.5 (10.5–10.6)  | 10000 + 0        | 590000 B     |            72.2 | 20109 / 17771 / 9842                | 0 / 0    |

`small-entries`:

| Configuration | Δ RSS at end / peak, MiB | Values + aliases | Charged BSON | Warm hit rate % | Origin queries: cold / warm / evict | Declines |
| ------------- | ------------------------ | ---------------- | ------------ | --------------: | ----------------------------------- | -------- |
| baseline      | 45.6 / 45.6 (45.5–45.8)  | 71089 + 0        | 4194251 B    |           100.0 | 64000 / 0 / 36000                   | 0 / 0    |
| disabled      | 46.0 / 46.0 (45.9–46.0)  | 71089 + 0        | 4194251 B    |           100.0 | 64000 / 0 / 36000                   | 0 / 0    |
| example       | 35.1 / 35.2 (35.1–35.2)  | 50000 + 0        | 2950000 B    |             0.0 | 64000 / 64000 / 36000               | 0 / 0    |
| count         | 11.1 / 11.1 (11.0–11.1)  | 10000 + 0        | 590000 B     |             0.0 | 64000 / 64000 / 36000               | 0 / 0    |
| key           | 45.9 / 45.9 (45.9–46.0)  | 71089 + 0        | 4194251 B    |           100.0 | 64000 / 0 / 36000                   | 0 / 0    |
| both          | 11.0 / 11.0 (11.0–11.2)  | 10000 + 0        | 590000 B     |             0.0 | 64000 / 64000 / 36000               | 0 / 0    |

What the tables establish:

- **The entry count bounds memory in proportion to the entries kept.** 10,000 entries leave 46 MiB with long filters (−84% in `large-keys`, −69% in `skewed-keys`) and 11 MiB with short ones (−76% in `small-entries`, −57% in `skewed-entries`).
- **The key limit removes the long-filter entries entirely.** With 2,048 bytes, `large-keys` and `skewed-keys` retain nothing and decline 164,000 admissions; Δ RSS falls to 5 MiB. It does nothing for short keys (`key` equals `disabled` in the short-filter scenarios), because those keys already fit.
- **Coverage is the price.** The sequential scans cycle 64,000 keys through a smaller LRU, so no warm read hits: with 10,000 or 50,000 entries the warm hit rate falls from 100% to 0% and every warm read becomes a database query (64,000 more). Under the skewed pattern, 10,000 entries keep 72.2% of warm reads in the cache instead of 82.5%, at 17,771 instead of 11,177 warm queries. A key limit that declines every long filter returns all reads to the database (0% hits), as the declines show.
- **The deployment guide's example limits bound entries, not memory.** With long filters, 50,000 retained entries still cost 212 MiB; the right limits come from the key size of the application's own filters.

### Unique keys and capacity pressure

One-query controls used 4,096 reads per phase and a unique `code` index. With
one record slot, admission retained one namespace value and no alias; a later
`_id` read required an origin query. With two slots it retained one identity
value plus one alias, and the `_id` read hit. At 128 aliases for one document,
the enabled policy retained one value and 128 aliases (2,259 charged BSON bytes),
versus 129 values plus 128 aliases (291,411 charged bytes) without the count
limit. Both needed zero origin reads after an unrelated write and 128 after a
matched write. This is a count-policy comparison, not a new invalidation rule.

Prefilled 128-record controls with 128 queries lost aliases under pressure:
subsequent identity and write phases needed 128 origin reads versus 0/0/1 in
unrestricted controls. The original-query repeat cost rose about 0.4–0.5 µs
where namespace fallback replaced alias resolution. Capacity tuning must account
for that lost reuse, not only the number of resident values. The
[API contract](../../docs/user/reference/api.md#optional-retention-limits) owns
pair admission, alias reclamation and fallback semantics.

### Cost of key sizing

Forty fresh processes per build/API isolated generous count-only, key-only,
both-limits and disabled configurations at equal residency: 4,096 distinct
one-field keys, 59-byte results, 4 MiB BSON budget. Cold reads admitted every key;
repeat reads hit. Measurements used process CPU, with CPU-2 affinity and a
low-priority busy loop on that CPU; they do not report wall-clock latency.

Count-only changes were unresolved within noise. Key-only sizing added about
3.5 µs sync and 3.7 µs async per admitted miss (paired changes +3.2%
[+1.4, +5.4] and +2.0% [+1.5, +3.5], bootstrap intervals). Both limits added
2–5 µs. Repeat-read intervals included zero change. Nine in-process rounds
measured a generic admission at 345 ns disabled versus 1,234 ns with key sizing;
that hot-object loop is a floor, not the cost between real requests.

The native walk sizes canonical tuples and shallow leaf objects. Its charge is
not retained RSS or a recursive measure of opaque scalar referents. Rejected
sizing alternatives and their correctness/resource constraints belong in the
[retention design](../../openspec/changes/archive/2026-11-04-bound-process-local-key-overhead/design.md).

## Reproduce

Use the [contributor environment](../../CONTRIBUTING.md) and disposable MongoDB:

```bash
source scripts/testcontainers-bridge.sh
uv run -- python -m research.process_memory.measure run --image docker.io/library/mongo:8.0.4-noble --runs 5 --output /tmp/agents/process-memory.json
uv run -- python -m research.process_memory.measure summarize /tmp/agents/process-memory.json
```

The current runner measures current code; use the named historical revisions
for historical comparisons. A full six-scenario run takes roughly two hours.
It measures fresh processes/containers in seeded random order, runs
`gc.collect()` before checkpoints, records RSS/USS/PSS, kernel phase peak RSS,
cgroup counters and residency, and separates close from diagnostic trimming.
Keep raw outputs untracked.

To repeat retention-pressure cells, seed 100,000 documents in
`process_memory.codes`, with `_id=i`, `code=f"C{i:07d}"`, `state="active"`
and a nonunique `code` index, using the same disposable replica-set fixture.
Run `python -m research.process_memory.measure child <uri> <scenario> <sync|async>
<direct|cached>` for the four named scenarios, adding `--max-entries 10000`,
`--max-key-bytes 2048`, both, or the example limits. Three repetitions per
configuration produced the pressure tables. Use the same installed candidate
wheel for direct and cached children and a new process each time.

`research.native_build_profile.limits` measures the isolated sizing floor;
`retention-child` in the memory runner measures equal-residency public reads.
The [historical procedure](https://github.com/alessio-locatelli/client-query-cache/blob/94065fbff5439c47268bd38e85b2101c95f9f30f/reports/process-memory/summary.md#test-cost-and-reproduction)
specifies unique-key fixtures, per-limit cells and wheel selection.

## Limits

One host per campaign; allocator versions, object shapes and filter reuse change
per-entry cost and post-close retention. Checkpoint GC excludes pending garbage.
Container counters and RSS charge shared/file pages differently. MongoDB memory
is excluded. Old results do not establish a current RSS ceiling, cross-host
latency bound or absence of leaks in other workloads.
