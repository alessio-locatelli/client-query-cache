# Tasks

The v8 outcome is preserved in
[`reports/worker-fault-recovery/research-outcome.md`](../../../reports/worker-fault-recovery/research-outcome.md).
This PR delivers the regression-coverage tasks below. The quantitative study
remains unfinished.

## 1. Regression coverage delivered by this PR

- [x] 1.1 Add a disposable three-member replica set and verify a real primary
      election.
- [x] 1.2 Add a test-only process-control harness using real direct and
      independently cached workers.
- [x] 1.3 Cover stepdown, TCP connection loss, independent stream-history loss
      and cache clearing, and worker kill/replacement with observable reads.

## 2. Quantitative study still pending

- [ ] 2.1 Validate a lower-overhead observer method in a small pilot and prepare
      a new registration. Preserve V8's inconclusive result and stop rule; do not
      weaken the acceptance gate.
- [ ] 2.2 Rebuild only the quantitative trial machinery required by that
      registration. Address the previous review findings for group recovery,
      stale-read reporting, replacement warmup, terminated-worker CPU and
      pre-injection write failures.
- [ ] 2.3 Run the full matrix only after the pilot passes. Publish measurements
      or operational guidance only when the completed evidence supports them.
