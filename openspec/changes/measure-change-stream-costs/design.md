## Context

See [proposal.md](proposal.md) for motivation. The foundation change chooses a
database-scoped stream manager and an inspection snapshot, but it does not yet
define how to separate stream polling, event delivery, local cache work, and
server CPU in measurements. The current source has no benchmark files or
benchmark dependencies, despite the README claiming that it is benchmarked and
stress tested.

MongoDB documents that a change stream holds a connection open in `getMore`.
PyMongo documents a 1,000 ms default `max_await_time_ms`; MongoDB also warns
that change streams cannot use oplog indexes and that many specifically targeted
streams can affect server performance. See [PyMongo change-stream options](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/monitoring-and-logging/change-streams/) and [MongoDB production recommendations](https://www.mongodb.com/docs/v8.0/administration/change-streams-production-recommendations/).

## Goals / Non-Goals

**Goals:**

- Measure cache benefit and stream activity at runtime with names that do not
  overclaim what they represent.
- Provide a reproducible benchmark protocol that compares equivalent cached and
  uncached workloads in idle and active stream phases.
- Reduce delivered event payload to invalidation and resume fields while
  retaining every event required for cache correctness.
- Publish workload-specific conclusions with versioned evidence.

**Non-Goals:**

- Derive a universal numeric break-even ratio, network-byte rate, or CPU cost.
- Treat application BSON size as encrypted, compressed, retransmitted, or total
  network bytes.
- Infer Atlas or production server CPU from a local Docker result.
- Add automatic cache disabling before a separately specified policy exists.
- Filter out correctness-relevant change events only to reduce traffic.

## Decisions

### Separate logical runtime metrics from physical measurements

Every manager reports cheap counters that work in normal deployments: cache
hits, misses, bypasses, admissions, rejections, evictions, invalidations,
avoided reads, stream polls, empty polls, received events, and BSON-encoded
logical event/value sizes. These answer whether the cache helped and how much
stream work reached the application.

They are intentionally not wire metrics. BSON sizes exclude MongoDB wire
headers, TLS, compression, TCP/IP headers, retransmission, and connection
setup; PyMongo does not expose stable per-command socket-byte counters. Counter
names use `logical` or `estimated`, and inspection exports this limitation.

### Proxy mode measures bytes only in a controlled topology

An optional benchmark-only TCP proxy sits between a dedicated benchmark client
and one direct local MongoDB endpoint. It counts bytes in both directions while
relaying unchanged traffic. Proxy runs disable TLS and compressor negotiation,
record direct-connection settings, and exclude discovery and unrelated traffic.
The result measures that path, not a production deployment.

Rejected alternatives:

- BSON-size inference is not labelled as wire traffic because it is not one.
- Host packet capture is not required because it needs elevated, non-portable
  tooling and is unsuitable for ordinary contributors and CI.
- Interface-wide byte counters are not used because they include unrelated
  traffic.

### Measure client and controlled-server CPU independently

The harness records monotonic wall time and process CPU time for the benchmark
client. In the local Docker Compose replica-set topology, it samples the MongoDB
container cgroup CPU usage before and after each phase. Reports label this
second figure `controlled_container_server_cpu`; arbitrary self-managed and
Atlas deployments retain only client measurements unless their operator adds an
external measurement source.

### Use paired, parameterized workload phases

Each run starts from the same seeded dataset. It compares raw primary/majority
reads with a warmed coherent cache using the same read profile. An optional
cache-store-only control measures encode/decode overhead but is not presented
as a coherent cache.

```text
seed data --> warmup --> sample raw reads
                     --> warm cache and stream --> sample cached reads
                     --> write workload --> sample invalidation and recovery
```

The required matrix covers idle, read-heavy/write-light, balanced, and
write-dominant phases; small, medium, and large BSON fixtures; insert, update,
replace, delete, and unrelated namespace writes; identity, bounded `find`, and
bounded aggregation reads; and one versus multiple cached collections served by
one database manager. Each variant repeats samples and reports latency median,
percentiles, and dispersion rather than one elapsed value.

### Project invalidation events, not full documents

The post-`$changeStream` projection keeps the unmodified event `_id`, operation
type, source namespace, document key, rename destination, cluster time, and
wall time. It excludes full documents, pre-images, and update descriptions.
The cache needs only identity eviction or a generation advance; it never
synchronizes a cached document from an event.

MongoDB states that update events normally provide deltas, inserts always
include `fullDocument`, and replacements include the new document. Projection
avoids delivering those potentially large values. MongoDB uses event `_id` as
the resume token and forbids a stream pipeline from modifying or removing it.
See [change-stream behavior](https://www.mongodb.com/docs/manual/changeStreams/) and the [replace-event reference](https://www.mongodb.com/docs/manual/reference/change-events/replace/).

The pipeline cannot omit inserts: an insert can invalidate a cached negative
lookup or a query, count, distinct value, or aggregation result. A future
selective filter needs a separate proof that it preserves all enabled cache
semantics and resumability.

## Benchmark Result Schema

Each versioned JSON result records:

```text
identity: library revision, Python/PyMongo/MongoDB versions and image digest
environment: host CPU/OS, container limits, topology, TLS/compression, pool size
workload: data, document sizes, operations, concurrency, cache/stream settings,
          warmup and sample schedule
measurements: latency, wall/client CPU, controlled-container CPU, logical cache
              and stream metrics, optional proxy bytes
limits: measurement mode and intentionally unmeasured fields
```

The generator validates required fields and fails instead of producing a report
presented as complete when a required topology or measurement source is absent.
Human-readable summaries are generated from JSON results.

## Risks / Trade-offs

- [A proxy changes the connection path] → Proxy results remain optional and are
  labelled with their direct, unencrypted, uncompressed conditions.
- [A local replica set is not Atlas or a production sharded cluster] → Every
  result identifies its topology; a sharded profile can be added separately.
- [Benchmark dependencies slow normal checks] → Benchmarks are opt-in and their
  schema/workload generator receive fast unit tests.
- [Metrics add overhead] → Use primitive counters and size payloads only when
  an event or cache admission is already being handled.
- [MongoDB changes event shapes] → Contract tests cover every retained event
  field and recovery uses exactly the production projection.

## Migration Plan

1. Implement the foundation manager and database stream first; this change has
   no standalone runtime target.
2. Add projection and logical measurements to the manager inspection surface.
3. Add the controlled benchmark topology, reports, and first reproducible runs.
4. Replace the README's unsupported benchmark claim with the protocol and
   linked reports only after reports exist.

Rollback disables the measurement and benchmark surfaces. The projection can
revert to a broader event shape without writing to MongoDB data.
