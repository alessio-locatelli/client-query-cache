# Shared identity misses without data-socket setup

The completed study for [#272](https://github.com/alessio-locatelli/client-query-cache/issues/272)
measured `56a837b22c3264a0038333fac9d4f5c7fd37c893`, a development revision
after 0.8.0. Its native control queue admitted valid local misses without first
opening a data socket or requesting an owner capture. Current shared ownership
has since moved into Rust; these are historical workload results, not current
release bounds. The [shared implementation guide](../../../docs/development/shared-cache.md)
owns present validity and fallback rules.

## Workload and inference

The frozen [configuration](config.json) and [environment](environment.json)
identify CPython 3.14.7, PyMongo 4.18.2, the Intel i3-13100 host, glibc 2.43 and
MongoDB 9.0.2 in a two-CPU/2-GiB single-member replica set. All three paths used
the same nested BSON catalogue (16,384 4-KiB-payload documents, seed 197),
primary/majority reads and decode/checksum work. Shared and per-worker independent
BSON budgets were each 96 MiB. Four/eight-worker cold windows issued 10,000
distinct misses at 1,000/s.

Each required cold cell used twelve fresh balanced blocks; inference resampled
whole blocks with 200,000 draws, both seeds and each block omitted in turn.
The 1 ms criterion applies to the additive latency upper bound over direct reads.
It is a workload acceptance criterion, not a latency SLA.

## Cold bounds

The limit is a 1 ms additive upper confidence bound over direct reads. Every cell contains twelve balanced blocks:

| Model | Workers | P95 point / upper ms | P99 point / upper ms | Outcome |
| ----- | ------: | -------------------: | -------------------: | ------- |
| async |       4 |        0.323 / 0.377 |        0.387 / 0.540 | pass    |
| async |       8 |        0.457 / 0.500 |        0.583 / 0.811 | pass    |
| sync  |       4 |        0.293 / 0.310 |        0.475 / 0.577 | pass    |
| sync  |       8 |        0.385 / 0.461 |        0.511 / 0.671 | pass    |

## Other acceptance margins

These are the recorded worst upper confidence bounds across cells in each phase;
they do not combine phases into a further confidence claim. Ratios compare shared
with the named baseline. Hit latency uses direct reads as its baseline.

| Phase                      | Measurement                                 | Recorded upper bound | Acceptance limit |
| -------------------------- | ------------------------------------------- | -------------------: | ---------------: |
| Hot                        | Group memory / independent                  |                0.709 |          ≤ 0.750 |
| Hot                        | Hit P99 / direct                            |                0.432 |          ≤ 1.000 |
| Hot                        | CPU per request / independent               |                0.837 |          ≤ 1.100 |
| Active                     | Request P99 / independent                   |                0.946 |          ≤ 1.250 |
| Active                     | Invalidation-lag P95                        |             16.20 ms |         ≤ 500 ms |
| Active                     | Added invalidation-lag P95                  |              4.33 ms |          ≤ 50 ms |
| Sorted find, eight workers | Group memory / independent, async / sync    |        1.033 / 1.055 |          ≤ 0.750 |
| Sorted find, eight workers | Request P99 / independent, async / sync     |        1.333 / 1.450 |          ≤ 1.250 |
| Sorted find, eight workers | CPU per request / independent, async / sync |        1.436 / 1.473 |          ≤ 1.100 |

Capacity recorded all 24 gates passing across 162 healthy windows. Its registered
throughput requirements were at least 0.900 times independent-cache capacity and
1.250 times direct-read capacity; the summary retained no numerical margins.
Active windows retained sixty seconds, 200 writes and mixed API workers. All 75
timed-fault trials passed. Large-document sensitivity passed; sorted
sixteen-document finds failed memory, CPU and P99 criteria, preventing a general
promotion claim. The later [sorted-find study](../sorted-find/results.md)
explains why the small catalogue could not amortize owner memory. Subsequent
collection support has its own [measurements](../collection-reads.md).

## Reproduction and evidence limits

Original raw acquisitions and one-off orchestration are unavailable. The summary
cannot independently verify the original confidence bounds. Fresh measurements
reproduce the protocol, not the original acceptance statistics.

At the named historical source, build with
`uv run -- maturin develop --release --locked` and source
`scripts/testcontainers-bridge.sh`. The [full registered procedure](https://github.com/alessio-locatelli/client-query-cache/blob/56a837b22c3264a0038333fac9d4f5c7fd37c893/reports/shared-worker-cache/v10/registration.md#reproduce)
defines qualification, baseline failure handling and phase invocation. Replace
performance configuration paths with v15. Resolve automated and manual
physical-host/baseline-source checks before candidate timing. Cold precedes
screening, confirmation, capacity, active and sensitivity; faults use the
separate [v8 fault configuration](../v8/fault-config.json).

Pin NumPy 2.3.4/SciPy 1.16.3 and `OPENBLAS_NUM_THREADS=1` for historical analysis.
Inspect analyzer verdicts and stability, not exit status alone. Raw outputs stay
untracked. Current tools still use historical configurations as protocol fixtures;
their presence does not establish current performance qualification.
