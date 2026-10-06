# Tasks

- [x] Establish the scalar rule with one-off raw-server differential experiments and record versions, outcomes, counterexamples, and exclusions in `reports/query-filter-normalization/summary.md`.
- [x] Capture baseline/final latency, key CPU, allocations, commands, and resident bytes as one-off measurements in the same report.
- [x] Implement the shared find-filter key helper and integrate it through the final native find shape in both cursor APIs.
- [x] Cover scalar permutations, type distinctions, ordered fallback, tag separation, and uncanonicalizable values through the full core key pipeline.
- [x] Align public cached-read docs, API reference, architecture, Context7 rules, and changelog with the implemented rule.
- [x] Retain focused cached-versus-native regressions for scalar reuse, ordered fallback, and native errors; remove the permanent raw semantic matrix and fixed server error codes.
- [x] Replace the experimental benchmark matrix with representative scalar key-cost workloads, removing the unrelated instrumentation rewrite while retaining failure cleanup.
- [x] Consolidate the durable and delta specs into the feature's actual identity contract, and distinguish historical experiments from ongoing checks in the evidence report.
