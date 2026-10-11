# Concurrent worker workload

This study measured how direct MongoDB reads compare with independent per-worker cache managers when several application worker processes serve reads while writes change the documents they read. It gives the [shared-invalidation investigation #87](https://github.com/alessio-locatelli/client-query-cache/issues/87) a steady-state baseline and complements the [shared worker cache study](shared-worker-cache-feasibility.md), whose registered mixed phase never ran. The comparison is descriptive: nothing ships from it, so it has no promotion gate.

**Result:** at a fixed 1,831 reads/s with one update per 20 reads, independent managers cut median request latency by about 40% at one and four asyncio workers and cut worker CPU per request, but they raised MongoDB CPU by about 10% and group memory by about 5 MiB per worker. The latency tail improved strongly with one worker and only slightly with four.

## What was measured

The [version 1 registration](../../../reports/concurrent-worker-workload/v1/registration.md) and its frozen [configuration](../../../reports/concurrent-worker-workload/v1/config.json) define the workload, measures and analysis. In short:

- **Direct** workers read MongoDB with primary read preference and majority read concern.
- **Independent** workers each own a supported `CacheManager` with a 96 MiB budget and their own change stream.

One or four asyncio worker processes, each with four requests in flight, issue `find_one({"_id": key})` on an open-loop schedule of 1,831 reads/s in total. Every worker walks its own seeded permutation of a 1,024-document hot set (about 4.3 MiB of encoded 4 KiB documents), so no key belongs to one worker, as with a load balancer. A harness writer pool issues 5,493 `$inc` updates per 60-second window, one per 20 offered reads, cycling through the hot set. Each worker reads the whole hot set before the window. Latency runs from each request's scheduled issue time, so queueing counts. The steady phase ran 12 blocks, alternating the path order by block parity, and every window recreated the data, processes and caches.

## Calibration

Read-only closed-loop probes found one direct worker to be the weakest cell at about 4,900 reads/s, which proposed 3,663 reads/s. With writes running, one of its one-worker direct validation windows ended with 9 requests outstanding against a bound of 8, so the registered rule halved the rate once to 1,831 reads/s, which every validation window sustained. The [calibration result](../../../reports/concurrent-worker-workload/v1/registration.md#calibration-result) records the probe ranges and dispatch lateness.

## Results

All 48 steady windows were healthy, met the registered overload rule and opened exactly one change stream per cached worker and none for direct reads, so the analysis excluded none. Estimates pair the 12 blocks: the ratio is `mean(independent) / mean(direct)` and the delta is the mean of the block differences, each with a 95% block-bootstrap percentile interval (200,000 draws, seed 197). The direct and independent columns are means over blocks.

| Workers | Measure                       |    Direct | Independent | Ratio (95% interval) | Delta (95% interval)       |
| ------: | ----------------------------- | --------: | ----------: | -------------------- | -------------------------- |
|       1 | Throughput, reads/s           |     1,831 |       1,831 | ×1.000 (1.000–1.000) | +0.03 (+0.02 to +0.05)     |
|       1 | Request P50                   |   1.13 ms |     0.67 ms | ×0.589 (0.573–0.601) | −0.47 ms (−0.50 to −0.44)  |
|       1 | Request P95                   |   4.02 ms |     1.63 ms | ×0.406 (0.372–0.439) | −2.39 ms (−2.75 to −2.07)  |
|       1 | Request P99                   |   9.49 ms |     3.97 ms | ×0.419 (0.374–0.462) | −5.51 ms (−6.56 to −4.65)  |
|       1 | MongoDB CPU per window        |    10.6 s |      11.5 s | ×1.090 (1.063–1.118) | +0.9 s (+0.7 to +1.2)      |
|       1 | Worker CPU per completed read |    374 µs |      271 µs | ×0.725 (0.712–0.738) | −103 µs (−109 to −97)      |
|       1 | Harness CPU per window        |     3.6 s |       6.9 s | ×1.953 (1.903–2.005) | +3.4 s (+3.3 to +3.5)      |
|       1 | Steady group PSS              |  52.4 MiB |    57.6 MiB | ×1.100 (1.099–1.102) | +5.2 MiB (+5.2 to +5.3)    |
|       1 | Peak group PSS                |  54.9 MiB |    59.9 MiB | ×1.091 (1.090–1.092) | +5.0 MiB (+4.9 to +5.1)    |
|       4 | Throughput, reads/s           |     1,831 |       1,831 | ×1.000 (1.000–1.000) | 0 (−0.01 to +0.01)         |
|       4 | Request P50                   |   1.58 ms |     0.98 ms | ×0.621 (0.608–0.631) | −0.60 ms (−0.64 to −0.57)  |
|       4 | Request P95                   |   4.01 ms |     3.77 ms | ×0.940 (0.932–0.949) | −0.24 ms (−0.27 to −0.21)  |
|       4 | Request P99                   |   5.90 ms |     5.27 ms | ×0.894 (0.858–0.930) | −0.63 ms (−0.85 to −0.41)  |
|       4 | MongoDB CPU per window        |    24.9 s |      27.3 s | ×1.099 (1.069–1.125) | +2.5 s (+1.8 to +3.0)      |
|       4 | Worker CPU per completed read |    948 µs |      893 µs | ×0.942 (0.920–0.960) | −55 µs (−78 to −37)        |
|       4 | Harness CPU per window        |     8.1 s |       9.7 s | ×1.204 (1.181–1.223) | +1.6 s (+1.5 to +1.8)      |
|       4 | Steady group PSS              | 183.8 MiB |   204.9 MiB | ×1.115 (1.114–1.115) | +21.1 MiB (+20.9 to +21.2) |
|       4 | Peak group PSS                | 186.0 MiB |   208.5 MiB | ×1.121 (1.120–1.122) | +22.5 MiB (+22.3 to +22.7) |

CPU per window covers the 60-second application window and the drain. MongoDB CPU is the replica-set container's cgroup; worker CPU includes each worker's embedded MongoDB byte proxy; group PSS counts worker processes, and PSS splits shared pages so that each counts once.

**Cache outcomes.** Every block recorded the same counts, because the read and write schedules are seeded. With one worker, the manager recorded 104,394 hits and 5,466 misses per window (95% hits); with four, the managers recorded 88,308 hits and 21,552 misses in total (80% hits). Every update invalidates the entry in every worker, so each worker pays its own miss after each write. No window recorded a bypass. As a descriptive aside outside the registered measures, the workers' MongoDB traffic fell from 546 MB per window to 33 MB with one worker and to 131 MB with four.

**Invalidation lag.** Each manager kept its last 1,000 invalidations, so every window met the 200-event floor. Lag is the worker host's wall clock when the manager applied the invalidation minus the change event's `wallTime`, the MongoDB server's wall clock at commit, adjusted by the server-minus-host offset estimated from `hello` samples. Block means of the pooled P50 were 6.0 ms with one worker (range 4.7–6.6 ms) and 6.6 ms with four (4.5–7.3 ms); P95 was 8.7 ms (6.5–10.1 ms) and 9.3 ms (6.2–11.2 ms). The calibrated offset stayed between −0.95 and +0.01 ms, and the offset uncertainty averaged 3.5 ms with one worker and 4.2 ms with four, so lag differences below a few milliseconds are not resolved.

## Where the CPU went

Worker processes used most of the CPU on both paths: about 41 s per window for one direct worker and 104 s for four, against 11–27 s for MongoDB. The cache removed the reads it answered from the workers' MongoDB round trips, so one cached worker spent 27% less CPU per read. At four workers, CPU per read was 2.5 times the one-worker value for direct reads and 3.3 times for cached reads, at the same aggregate rate, and MongoDB CPU was 2.4 times higher. The workload was not profiled, so this study does not attribute that growth; fixed per-process work and contention for the host's four physical cores, which also run the harness and MongoDB, are both consistent with it. The same contention is the likely reason the four-worker latency tail improved far less than the one-worker tail.

MongoDB CPU did not fall with caching. MongoDB still processed every update, fed each worker's change stream and served every miss after an invalidation; at one update per 20 reads, the CPU saved on the reads that the caches answered did not offset that work. The cached harness also used more CPU. The harness includes the 200 ms PSS sampler, the clock observer, the writer pool and its byte proxies; the drain was equally short on both paths, and the difference was not attributed further.

## Excluded comparison

A shared Redis cache was not compared. It would match this library's freshness only with an invalidator for every MongoDB write, either application write-path deletes, which miss other writers, or a change-stream consumer that this project would have to build and operate. Either way the comparison would measure that invalidator and Redis's network round trip, not a deployment choice available to users of this library, and a TTL-only Redis setup offers different freshness. Shared invalidation stays under [#87](https://github.com/alessio-locatelli/client-query-cache/issues/87).

## Limitations

The measurements cover one host with eight logical CPUs (Intel Core i3-13100, four cores), Linux 7.2.9, Python 3.14.7, PyMongo 4.18.2, psutil 7.2.2, and MongoDB 8.3.11 in a single-member replica set limited to two CPUs and 2 GiB. The host was not dedicated to the benchmark. Calibration selected the rate against MongoDB 8.0.4, because the branch was rebased onto a newer harness image while it ran; every steady window on 8.3.11 also met the registered overload rule, so the frozen rate stayed below saturation for both paths. One host and a local replica set understate network latency, which a cache hit avoids, and overstate the CPU that direct reads compete for. The workload has one database, uniform key popularity, 4 KiB documents, asyncio workers and one write per 20 reads; other write rates, document sizes, worker counts or a remote MongoDB can change every result.

## Reproduce

Use the [contributor environment](../../../CONTRIBUTING.md) and configure the container bridge:

```bash
source scripts/testcontainers-bridge.sh
uv run -- python -m benchmarks.stream_cost.shared_cache.run --phase steady --config reports/concurrent-worker-workload/v1/config.json --output benchmark-reports/concurrent-worker-workload/steady.json
uv run -- python -m benchmarks.stream_cost.shared_cache.analysis benchmark-reports/concurrent-worker-workload/steady.json --config reports/concurrent-worker-workload/v1/config.json --phase steady --blocks 12
```

The steady phase takes about an hour; a run interrupted by the host can continue with `--resume <earlier report>`. The smoke check and calibration commands are listed in the [registration](../../../reports/concurrent-worker-workload/v1/registration.md#reproduction). The steady phase ran at revision `23a6fb7ddda311851d8f452cd3cf921eb10fce35` with configuration SHA-256 `2057af0088101622b441f977fbc9bd78397f2e023fafd8b092cc1e74d1b6d0bc`. Raw reports remain untracked.
