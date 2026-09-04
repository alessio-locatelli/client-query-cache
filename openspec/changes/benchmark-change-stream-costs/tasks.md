## 1. Add safe telemetry

- [ ] 1.1 Implement immutable cache-benefit, stream-poll, logical-event-byte, invalidation, and resident-byte snapshots with scope metadata; verify serialization redacts documents, queries, credentials, and resume tokens.
- [ ] 1.2 Verify projected stream events preserve invalidation/resume semantics without full-document update lookup; verify event fixtures cover every supported operation type.

## 2. Build controlled measurement infrastructure

- [ ] 2.1 Add benchmark configuration, seeded BSON generators, versioned JSON schema, and a report validator; verify incomplete identity, environment, workload, or limitation data is rejected.
- [ ] 2.2 Add isolated replica-set setup, resource limits, a dedicated benchmark client, and optional direct-path proxy; verify unavailable Docker, cgroup/runtime CPU evidence, TLS, compression, discovery, or shared-connection conditions fail clearly.

## 3. Measure comparable workloads

- [ ] 3.1 Implement paired raw/cache idle, read-heavy, balanced, and write-dominant workloads over small, medium, and large BSON data; prime every cache workload/data-size variant through normal admissions and verify positive admission and hit counter deltas for each variant before sampling, identical workload parameters, correct returned data, exactly one consolidated stream across at least two cached collections in one database, and separately identified relevant and unrelated writes in that same database.
- [ ] 3.2 Record aggregate wall time, per-variant latency distributions with cache-outcome labels for operation-bearing variants, an explicit zero-operation/no-latency-samples marker for idle variants, benchmark-process CPU, mandatory controlled container CPU, per-variant warmup counter deltas, logical metrics, and optional direct-path bytes with their limitations; verify unavailable container CPU fails controlled runs and reports never relabel logical or proxy bytes as universal wire traffic.

## 4. Publish evidence without timing gates

- [ ] 4.1 Retain initial versioned reports and workload-selection guidance; verify every conclusion identifies its exact workload and report.
- [ ] 4.2 Add an opt-in CI benchmark workflow that uploads reports without a host-dependent regression threshold; verify normal CI does not run it.
