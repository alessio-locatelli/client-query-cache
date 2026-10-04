# Concurrency stress tests

The integration suite checks mixed concurrent reads and external inserts, updates, replacements, and deletes against a disposable MongoDB replica set. Each case owns one manager. The synchronous case uses reader threads; the asynchronous case uses reader tasks.

Run the default workload and controlled race cases:

```console
just pytest -- -q tests/stress
```

Four background readers visit two hot identities and eight cold identities across two collections. Each hot identity receives four times the background read traffic of each cold identity. A deterministic cycle issues 40 external writes and 320 exact checkpoint reads. Each cycle has four ten-write CRUD phases. At every phase boundary, all four readers must still be running and each must have completed at least ten reads during that phase. The writer does not wait for readers to catch up. The default is two cycles per execution model.

Background reads reject document versions older than invalidations processed before the read starts. Exact checkpoints after each processed write also check deletion and insertion after cached negative results. Repeated checkpoint reads must issue no MongoDB reads for either query shape, including when the result is `None`. A healthy stream alone does not establish that a write has been processed. A database read already in flight may return its earlier value, but must not cache it after an intervening invalidation.

The controlled race cases pause identity and namespace reads after a real database response. They release the read after either a real invalidation or stream recovery and verify that it publishes no new cache entry. Recovery cases inject a disconnection and unavailable resume history into the live stream, hold successful reopening, and verify that active readers cannot use or populate the cache during that interval. A subsequent external write verifies that the reopened stream resumes invalidation.

For a longer local run, increase the cycle count and timeout together:

```console
just pytest -- -q tests/stress --stress-cycles=20 --timeout=300
```

`--stress-cycles` accepts positive integers. Pytest's configured 30-second timeout bounds each default test; `--timeout` changes that bound. The suite uses pytest-timeout's thread timer to terminate a stalled process, including deadlocked reader threads. Worker exceptions also fail the run. These tests assert correctness without imposing throughput or latency thresholds. They do not cover multiple managers or shared caches across processes.
