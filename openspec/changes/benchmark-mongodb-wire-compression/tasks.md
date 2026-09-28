# Tasks

## 1. Compression-capable measurement path

- [ ] 1.1 Add the benchmark-only Snappy dependency and a four-mode dedicated-client configuration using Python 3.14's built-in Zstandard and zlib modules; verify each requested mode reaches PyMongo and missing optional modules fail setup visibly.
- [x] 1.2 Let the direct-path proxy forward compressed traffic while retaining its TLS, discovery, and shared-connection guards; verify unit and isolated-server cases count compressed path bytes in both directions.
- [ ] 1.3 Add isolated-server compressor preflight through the measured client, with a separate uncompressed admin sampler; verify tests reject unavailable, unnegotiated, or mislabeled modes before sampling.

## 2. Matched workload runner

- [ ] 2.1 Add the idle, balanced, and write-heavy small/large schedules and repeat/order configuration; verify schedule and counterbalancing tests cover all four modes and both paths.
- [ ] 2.2 Run fresh no-stream and primed stream-watching windows under each mode using the existing replica set, CPU sampler, and proxy; verify integration cases detect mismatched operations, missed write timing, unhealthy streams, or missing events.
- [ ] 2.3 Collect read, write, and monotonic write-to-invalidation samples from matched windows, including idle zero-sample markers; verify integration cases produce finite CPU, latency, and byte values for all four modes.

## 3. Report and decision

- [ ] 3.1 Add a separate versioned compression report schema and validator covering all raw windows, metadata, negotiation evidence, scope limits, per-mode stream-minus-control values, and missing-data rejection; verify report tests accept a complete matrix and reject incomplete or mislabeled cases.
- [ ] 3.2 Implement the pre-registered CPU, invalidation-latency, and total-byte decision rule with an explicit inconclusive outcome; verify parameterized cases for a qualifying mode, CPU or latency regression, insufficient byte savings, and noisy idle data.

## 4. Retained evidence and public guidance

- [ ] 4.1 Run the full isolated four-mode matrix and retain its validated versioned report; verify it contains repeated matched CPU, latency, and byte measurements with no missing mode or path.
- [ ] 4.2 Document the measured default in `docs/stream-cost-benchmarks.md` and link it from the README as needed, including PyMongo configuration, stream-cost rationale, limitations, and reproduction command; verify every numeric claim against the retained report and the command against the implemented runner.

## 5. Code Quality

- [ ] 5.1 Scan every edited or added test file, including pre-existing tests within those files, for compliance with the `AGENTS.md` Writing Tests guidelines; verify repeated cases use parametrization and reusable setup.
- [x] 5.2 Not applicable: the Claude Code prose restriction does not apply to OpenAI Codex.
