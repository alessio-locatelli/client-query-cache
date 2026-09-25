# Tasks

## 1. Guarded workloads

- [x] 1.1 Add bounded synchronous and asynchronous cached-read hit cases using real cache behavior and existing seeded data; verify their unit/integration tests assert returned results and hit outcomes for both document profiles.
- [x] 1.2 Add bounded multi-document admission and populated-entry change-event invalidation cases; verify tests reject a bypass, missing admission, missing invalidation, or wrong result before timing is accepted.
- [ ] 1.3 Reuse the existing workload generators, replica-set setup, and observability snapshots where applicable; verify the guard cases run without the 12-variant controlled matrix or decision-evidence runner.

## 2. Relative comparison

- [ ] 2.1 Add a runner that identifies exact base and tested PR revisions, applies one workload definition and equivalent seeded state to both, and alternates warm, isolated measurement blocks on one runner; verify tests detect revision, workload, environment, and outcome mismatches.
- [ ] 2.2 Add a predeclared 30% material-slowdown rule with a stability bound and fixed sampling budget; verify deterministic tests distinguish clear regressions, ordinary noise, inconclusive comparisons, and missing/invalid baseline measurements.
- [ ] 2.3 Produce concise per-case diagnostics and a bounded machine-readable result; verify tests cover failure and inconclusive output without including document contents or credentials.

## 3. Pull-request integration and guidance

- [ ] 3.1 Add a stable, unprivileged PR check that times relevant Python/dependency/guard changes, explicitly skips unrelated changes, enforces a runtime limit, and preserves targeted diagnostics; verify its event and path decisions for Python, dependency, guard, and documentation-only changes.
- [ ] 3.2 Update `docs/stream-cost-benchmarks.md` to explain the guard's scope, the manual workflow's separate purpose, inconclusive results, and human-reviewed intentional trade-offs; verify the documented result fields and process match the check.

## 4. Gate rollout

- [ ] 4.1 Run the new workload against both revisions for the introducing PR, then perform clean-base self-comparisons and an intentionally slowed candidate on a CI-like runner; record observed stability, detected slowdown, and elapsed job time, and verify the configured boundary catches the seeded regression without noisy self-comparison failures.
- [ ] 4.2 After the guard definition reaches the base branch, have repository administrators configure an auditable, maintainer-only merge-rule exception and document the accepted-slowdown review process; verify PR authors cannot use the exception or suppress a red guard result.
- [ ] 4.3 Configure the stable guard check as required in merge rules only after task 4.2, then verify a deliberately failing guard blocks an ordinary PR while documentation-only PRs receive a successful skip.

## 5. Code Quality

- [ ] 5.1 Scan every edited or added test file in full, including pre-existing tests in those files, for the `AGENTS.md` Writing Tests rules; verify parametrization, fixture cleanup, and realistic generated values are applied where relevant.
- [x] 5.2 Inapplicable for OpenAI Codex: the Claude Code prose restriction does not apply.
