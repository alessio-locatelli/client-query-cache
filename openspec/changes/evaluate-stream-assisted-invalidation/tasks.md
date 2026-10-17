# Tasks

## 1. Projection evaluation

- [x] 1.1 Add `research/invalidation_scope/stream_projection.py` using the acquisition protocol in `design.md`; verify bounded projections and event accounting against the isolated server before recording timings.
- [x] 1.2 Run the registered matrix without competing validation processes; publish measurements, separate policy status and reproduction commands in `docs/development/research/stream-assisted-invalidation.md`, and link it from the invalidation-scope report.
- [x] 1.3 Correct the premature transport-only completion claim and extend this change with the end-to-end evaluation requested in review.

## 2. End-to-end evidence

- [x] 2.1 Add fixed-workload research guards using native cache reads and stream processing; qualify freshness, conservative fallbacks and admission races against real MongoDB.
- [x] 2.2 Add the end-to-end runner and pilot its correctness/acquisition cost; pin decision-run parameters before gathering decision evidence.
- [ ] 2.3 Measure both hypotheses independently, including actual saved reads, router CPU, warm hits and unrelated/uncached controls; resolve noisy comparisons with matched repetitions.
- [ ] 2.4 Publish the measured net-benefit decisions and reproduction commands, and align #257 and PR #297 with those completed acceptance criteria.

## 3. Code Quality

- [x] 3.1 Scan edited or added test files against the Writing Tests guidelines, including parametrization (inapplicable: no test files changed; live verification belongs to the research runner).
- [x] 3.2 Confirm no new prose was added by Claude Code (inapplicable: implemented by Codex).
