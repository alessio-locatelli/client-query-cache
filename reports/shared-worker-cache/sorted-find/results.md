# Small shared catalogues and publication cost

This October 2026 study at `108cc371f542e281e57d84fed66e2aebead70edf`
measured local publication of sorted find results. The public API has since
expanded; current eligibility belongs in the
[shared reference](../../../docs/user/reference/shared-cache.md).

## Workload and conditions

CPython 3.14.7, PyMongo 4.18.2, psutil 7.2.2, Testcontainers 4.15.0,
Intel i3-13100, Fedora/Linux 7.2.10, glibc 2.43, Rust 1.99.0 and Maturin 1.15.0.
MongoDB 9.0.2 had two CPUs and 2 GiB. The [configuration](config.json) used
eight spawned workers, four in-flight reads each, three balanced blocks at
319 reads/s for 32 seconds after ten seconds warmup. Each cached window served
10,208 hits and no misses. Shared hits issued no selection RPC/data-channel
bytes; recency notifications still ran.

The 16,384-document catalogue had 64 categories, 4-KiB payloads and sixteen
sorted results per query. Shared and independent BSON budgets were each 96 MiB.
The encoded result catalogue was only 4.264 MiB.

## Fixed footprint and invalidation

| Observation                           |          Sync |         Async |
| ------------------------------------- | ------------: | ------------: |
| Independent group PSS, MiB            | 390.03–390.10 | 388.87–389.12 |
| Shared group PSS, MiB                 | 405.73–406.01 | 402.71–403.01 |
| Shared/independent CPU ratios         |   1.014–1.057 |   0.987–1.211 |
| Shared/independent request P99 ratios |   1.026–1.068 |   0.971–1.029 |

Group PSS includes workers plus owner; CPU includes those processes and MongoDB
through drain, excluding the harness. The 0.75 memory-ratio target was below
even the direct workers' 355–358 MiB footprint. Saving seven duplicate copies
of 4.264 MiB could not amortize the owner/index. Removing RPCs cannot remove
worker baseline memory. MongoDB cgroup snapshots grew across the reused container,
so they do not establish path-specific total savings. These ranges are descriptive.

A separate isolated invalidation diagnostic published 66,051-byte results and
measured five batches of `record_write`, excluding population and MongoDB:

| Published shapes | Writes/batch | Median CPU µs/write |
| ---------------- | -----------: | ------------------: |
| 1                |          500 |               2.648 |
| 64               |          100 |              20.760 |
| 1,024            |           20 |             454.305 |

Invalidation was linear in published shapes. This informs consideration of
high-cardinality publication, but native shared ownership later changed this
path. Remeasure before making a current performance decision.

## Reproduce

At the named source, build the release extension and run the shared-cache
benchmark's `sensitivity` phase with
`reports/shared-worker-cache/sorted-find/config.json`. Keep all models/paths
and three blocks; inspect health, outcomes and `block_statistics`. The historical
[invalidation harness](https://github.com/alessio-locatelli/client-query-cache/blob/ff9153499b5e00054a2b91cf17cc852522cd13b1/research/sorted_find/invalidation.py)
is available through Git. Raw outputs stay untracked; fresh acquisitions cannot
reconstruct disposed observations. The [collection-read study](../collection-reads.md)
measures a different, later broad-API workload.
