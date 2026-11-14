# Why shared hits validate locally

Current shared ownership and validity belong in the
[implementation reference](../shared-cache.md). This historical study explains
why replacing payload storage alone would not solve a Python owner round trip.
Use the [public measurements](../../user/benchmarks/shared-cache.md) for the
dated public-API workload comparison.

## Socket-owner evidence

At `5ceb0c3a981572c1f465ba113c58d60d4e935bb1`, six screening blocks compared
direct reads, independent 96 MiB caches and one shared 96 MiB cache. Each worker
primed the 16,384-document catalogue (68.3 MiB encoded), then issued four
concurrent reads on an open-loop 1,267 reads/s aggregate schedule for thirty
seconds. Every window recreated processes, caches and data; latency included
dispatch queueing. The [frozen input](../../../benchmarks/stream_cost/shared_cache/fixtures/v4/config.json)
retains exact workload and gate definitions.

Host: Intel i3-13100, eight logical CPUs, Linux 7.2.9, Python 3.14.6,
PyMongo 4.18.2, MongoDB 8.0.4 in a two-CPU/2-GiB single-member replica set.
The host also ran a browser/video service using about 0.3 CPU. These are
historical prototype observations, not current native-cache costs.

| Cell                 | Shared/independent group PSS | Shared/independent request P99 | Shared/independent total CPU/read |
| -------------------- | ---------------------------: | -----------------------------: | --------------------------------: |
| Sync, four workers   |                         0.61 |                           1.69 |                              1.65 |
| Async, four workers  |                         0.60 |                           1.34 |                              1.82 |
| Async, eight workers |                         0.48 |                           1.31 |                              1.71 |

Ratios use means of block statistics. CPU includes workers, owner and MongoDB
through drain. PSS counts owner plus workers, not MongoDB. The synchronous
eight-worker registered cell exhausted connections and cannot support a clean
comparison; its later exploratory rerun is excluded here. The unaffected cells
already exceeded the 1.25 P99 and 1.10 CPU limits, stopping the candidate before
confirmation or capacity acquisition.

Owner cost was about 120–135 µs/read, mostly parsing/dispatch, validity checks
and guarded lookup. Encoding and sending the 4-KiB reply each accounted for
less than 3% of instrumented owner time. LMDB or shared payload storage that
retained selection RPCs could not remove the dominant cost. No second payload
prototype was justified. The later native-index floor at `eadca6fe` measured
caller-plus-owner CPU around 5.8–6.9 µs/hit, versus 11–13 µs for the Python
core, motivating local validity checks. Floors omit facade work and do not
predict application latency.

## Later evidence and reproduction

The [identity-miss study](../../../reports/shared-worker-cache/v15/results.md)
retains the completed cold-bound comparison and its lost-raw-data limitation.
The [small-catalogue study](../../../reports/shared-worker-cache/sorted-find/results.md)
shows why saving payload copies need not amortize the owner, and the
[duration study](../../../reports/shared-worker-cache/runtime/empirical-results.md)
records acquisition constraints. These workloads answer different questions.

To repeat the socket prototype, check out the named historical source and run
the benchmark's `screening` phase with its v4 configuration, then analyze six
blocks. The current runner's default still loads that input, but current native
code does not recreate the Python owner measured here. The
[original registration](https://github.com/alessio-locatelli/client-query-cache/blob/243cbfb790766e9ee25b3ecced1ffe83e96d083c/reports/shared-worker-cache/v4/registration.md)
provides calibration and reproduction commands. Keep raw outputs untracked;
use a fresh registered current-code comparison for present engineering decisions.
