# Find limit subsumption measurements

Measured on 2026-10-05: Fedora 44 Toolbx, Linux 7.2.8, Ryzen 3 210
(four cores/eight threads), CPython 3.14.6, PyMongo 4.18.2, and a disposable
MongoDB 8.0.4 replica set. The cache uses a 64 MiB stored-BSON budget and a
1 MiB entry cap. Timed runs had no simultaneous test workloads.

## Cursor reads

The server workload uses 240 ordered documents, 64-byte or 4,096-byte payloads,
unlimited/240/sixteen distinct source limits, both admission orders, and zero or
128 unrelated entries. Warmup forces exact lookup so descending admission also
creates every source. General phases use normal lookup; focused prefix cases
compare an isolated single-source exact-only control with compatible discovery
and vary admission order only for multi-source families. The control uses the
same cursor/admission code with namespace lookup in place of discovery. Medians use nine untraced reads after a separate traced read.

Single-limit, isolated ten-document prefix reads:

| API   | Payload bytes | Exact-only control, µs | Compatible, µs |
| ----- | ------------- | ---------------------- | -------------- |
| Sync  | 64            | 610                    | 201            |
| Sync  | 4,096         | 795                    | 336            |
| Async | 64            | 587                    | 211            |
| Async | 4,096         | 927                    | 336            |

Every control prefix read sends one find; every compatible read sends zero
find/getMore commands and preserves resident payload and entry count. Single
sources weigh 31,583/999,263 BSON bytes. Exact hits also avoid commands; cold,
negative-limit, and batching-bypass reads execute natively. Full-source decoding
produces prefix allocation peaks of 161–163 kB/1.13 MB, versus control peaks of
16–22 kB/140–142 kB. cProfile identifies BSON decoding and key canonicalization
among the largest costs. A smaller covering source reduces decoding work.

## Query size and admission order

The core workload admits empty results under 1, 16, or 64 limits, with predicates
containing 8 or 1,024 `$or` branches, each with a three-value `$in`. Requests are
built before timing; each lookup still canonicalizes and hashes the query.
Each cell is the median of twenty untraced lookups after one warmup lookup.

| Resident limits | 8 branches, ascending / descending, µs | 1,024 branches, ascending / descending, ms |
| --------------- | -------------------------------------- | ------------------------------------------ |
| 1               | 98 / 97                                | 11.04 / 10.49                              |
| 16              | 100 / 99                               | 10.13 / 10.52                              |
| 64              | 103 / 103                              | 10.26 / 10.08                              |

All cases perform two LRU probes: exact plus the smallest covering source.
Sorting the snapshot uses scalar limits in O(k log k); a valid smallest source
requires one full query comparison regardless of admission order. Colliding or
invalid candidates can require further comparisons/probes. Profiling attributes
large-predicate cost mainly to canonicalization; traced lookup peaks are about
7 kB/747 kB for small/large predicates. These samples do not establish bounds
for larger families or cross-host latency guarantees.

## Retained heap

Paired traced admissions compare exact-key storage with and without the family
index, using the same large predicate and empty payloads. After population returns
and garbage collection runs, sixteen sources retain about 16.93 MB of Python
heap plus 1.3 kB of incremental index overhead; sixty-four retain about 67.35 MB
plus 4.6 kB. Stored BSON weighs only 208/832 bytes. Namespace clear empties the
family buckets and leaves roughly 2–6 kB of traced bookkeeping allocations.
These are single observations; first-case and small differences include pytest
bookkeeping. Query keys and Python metadata remain outside the stored-BSON budget.

## Reproduction

```bash
just pytest -n 0 -m benchmark tests/benchmark/test_cached_read_cursors.py -k test_find_limit -q -s
just pytest -n 0 -m benchmark tests/benchmark/test_find_family_memory.py -q -s
```

The workloads print timings, command/probe counts, BSON weights, allocation
samples, and profiles. Tracing and profiling run outside timed samples; setup
is excluded. Keep redirected raw output untracked.
