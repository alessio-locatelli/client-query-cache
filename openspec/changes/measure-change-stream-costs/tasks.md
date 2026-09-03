## 1. Add cost-aware stream behavior

- [ ] 1.1 Implement the invalidation-only database stream pipeline that preserves the event `_id`, namespace, operation type, document key, rename destination, cluster time, and wall time while excluding full documents and update descriptions; verify fixture tests cover insert, update, replace, delete, drop, rename, and invalidate event shapes.
- [ ] 1.2 Verify the projected pipeline receives every event needed by document and derived-result invalidation and resumes with the identical options; verify an integration test warms a negative/query cache, inserts a matching large document, and proves the result is invalidated after stream recovery.
- [ ] 1.3 Add immutable manager measurement snapshots with cache-benefit, stream-poll, logical-event-byte, and no-resident-document counters; verify unit tests distinguish a hit, miss, bypass, empty poll, resident-document eviction, and unrelated event.
- [ ] 1.4 Add measurement scope metadata and safe structured logging so exported snapshots cannot be mistaken for wire-byte or server-CPU measurements and cannot contain queries, documents, credentials, or resume tokens; verify redaction and serialized-snapshot tests.

## 2. Build controlled measurement infrastructure

- [ ] 2.1 Add a benchmark command, configuration model, seeded BSON fixture generator, versioned JSON result schema, and report validator; verify schema and required-field tests reject incomplete identity, environment, workload, measurement, and limitation data.
- [ ] 2.2 Add an isolated local replica-set benchmark topology with primary election, explicit resource limits, and a dedicated benchmark client; verify setup fails clearly when Docker, the replica set, or cgroup CPU accounting is unavailable.
- [ ] 2.3 Add a benchmark-only TCP byte-counting proxy for a direct MongoDB connection; verify a proxy test counts bidirectional traffic and that proxy mode refuses TLS, compression, discovery traffic, or shared client connections.
- [ ] 2.4 Collect monotonic wall time, benchmark-process CPU time, and controlled MongoDB-container cgroup CPU deltas for each measured phase; verify a controlled fixture produces non-negative, correctly labelled measurements and reports missing sources as errors.

## 3. Implement comparable workload benchmarks

- [ ] 3.1 Implement paired raw-primary/majority and warm-coherent-cache runs that share seeded data, query shape, read/write mix, concurrency, duration, warmup, and sample schedule; verify the report validator rejects a comparison whose variants differ in any required parameter.
- [ ] 3.2 Add idle-stream workloads that run beyond the configured await interval and report polls, empty polls, wait time, client CPU, and logical event bytes; verify the result never presents logical bytes as wire bytes.
- [ ] 3.3 Add read-heavy/write-light, balanced, and write-dominant workloads across small, medium, and large BSON documents; verify results include latency distribution, cache outcomes, event activity, client CPU, and controlled-server CPU for every sampled variant.
- [ ] 3.4 Add identity lookup, bounded `find`, and bounded aggregation workloads, including insert, update, replace, delete, and unrelated-namespace writes with one and multiple cached collections; verify each workload asserts data correctness before writing a result report.
- [ ] 3.5 Add optional proxy-mode runs to measure the benchmark path's bytes for raw and cached variants; verify generated reports declare direct topology and disabled TLS/compression rather than extrapolating to production wire traffic.

## 4. Publish reproducible evidence and operating guidance

- [ ] 4.1 Remove the current unsupported README claims of complete coverage, benchmarking, and stress testing; verify project documentation makes no performance claim without a linked versioned report.
- [ ] 4.2 Document the benchmark protocol, prerequisites, workload matrix, result schema, measurement limits, and how to reproduce a run; verify every command works in the controlled local topology and documentation links resolve.
- [ ] 4.3 Run and retain initial versioned reports for the required logical-metrics workloads and, when the controlled proxy is available, proxy workloads; verify each retained report includes exact revision, versions, topology, resource limits, parameters, samples, and limitations.
- [ ] 4.4 Add workload-selection guidance that explains how to interpret avoided reads, event rate, logical payload, idle polls, CPU deltas, and invalidations; verify every stated conclusion links to a report and names the workload rather than claiming a universal break-even point.

## 5. Keep benchmarks reliable in development and CI

- [ ] 5.1 Add fast unit and integration checks for projection, metrics, proxy accounting, result-schema validation, and report generation; verify they run independently of long benchmark sampling.
- [ ] 5.2 Add an opt-in benchmark CI workflow or manual job that provisions the controlled replica-set topology and uploads JSON reports as build artifacts without using them as cross-host performance gates; verify the rendered workflow and a local equivalent command.
- [ ] 5.3 Run all relevant quality checks, inspect generated reports for environment labels and unsupported claims, and run `openspec validate measure-change-stream-costs --strict`; record exact verification output before marking the change complete.
