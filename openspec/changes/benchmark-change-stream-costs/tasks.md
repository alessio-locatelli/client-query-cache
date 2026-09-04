## 1. Add safe telemetry

- [ ] 1.1 Implement immutable cache-benefit, stream-poll, logical-event-byte, invalidation, and resident-byte snapshots with scope metadata; verify serialization redacts documents, queries, credentials, and resume tokens.
- [ ] 1.2 Verify projected stream events preserve invalidation/resume semantics without full-document update lookup; verify event fixtures cover every supported operation type.

## 2. Build controlled measurement infrastructure

- [ ] 2.1 Add benchmark configuration, seeded BSON generators, versioned JSON schema, and a report validator; verify incomplete identity, environment, workload, or limitation data is rejected.
- [ ] 2.2 Add isolated replica-set setup, resource limits, a dedicated benchmark client, and optional direct-path proxy; verify unavailable Docker, cgroup, TLS, compression, discovery, or shared-connection conditions fail clearly.

## 3. Measure comparable workloads

- [ ] 3.1 Implement paired raw/cache idle, read-heavy, balanced, and write-dominant workloads over small, medium, and large BSON data; verify variants have identical workload parameters and correct returned data.
- [ ] 3.2 Record wall time, benchmark-process CPU, controlled container CPU, logical metrics, and optional direct-path bytes with their limitations; verify reports never relabel logical or proxy bytes as universal wire traffic.

## 4. Publish evidence without timing gates

- [ ] 4.1 Retain initial versioned reports and workload-selection guidance; verify every conclusion identifies its exact workload and report.
- [ ] 4.2 Add an opt-in CI benchmark workflow that uploads reports without a host-dependent regression threshold; verify normal CI does not run it.
