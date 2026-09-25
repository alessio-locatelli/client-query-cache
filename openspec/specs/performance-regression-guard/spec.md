# performance-regression-guard Specification

## Purpose

This capability detects clear, material slowdowns in shipped cache hot paths introduced by a pull request using comparable measurements of the base and proposed revisions.

## Requirements

### Requirement: Pull requests exercise a bounded cache hot-path guard

CI SHALL run the guard for pull requests that change Python code, Python runtime dependencies, or inputs to the guard. It SHALL give the check a stable status for pull requests that do not affect these inputs. The guard SHALL cover representative synchronous and asynchronous cached read hits, cache admission, and change-event invalidation using the shipped implementation, including their associated cache outcomes. It SHALL remain bounded enough for ordinary pull-request CI and SHALL NOT require the full controlled stream-cost matrix or architectural decision workloads.

#### Scenario: A Python change affects a shared cache path

- **WHEN** a pull request changes Python code that may affect cached reads or invalidation
- **THEN** CI measures the guarded paths for the base and proposed revisions and reports a guard result

#### Scenario: A documentation-only change is proposed

- **WHEN** a pull request changes no Python code, Python runtime dependency, or guard input
- **THEN** the guard reports a successful, explicit skip without running timed workloads

#### Scenario: A case never exercises its claimed cache outcome

- **WHEN** a timed case does not produce its required hit, admission, or invalidation outcome
- **THEN** its measurement is rejected rather than compared as valid performance evidence

### Requirement: Guard decisions use matched relative evidence

For each guarded case, CI SHALL compare the proposed implementation with the pull request's base revision on the same runner and compatible runtime, using the same workload definition and input data for both. It SHALL identify both revisions and the workload definition used. The comparison SHALL repeat measurements in counterbalanced order with warmup and SHALL use a predeclared material-regression boundary of 30% relative slowdown, together with a predeclared stability rule that accounts for observed run-to-run variation. A case SHALL fail for performance only when the evidence clearly exceeds that boundary. Fixed historical durations or timings from a different host SHALL NOT decide the guard status.

#### Scenario: A stable material slowdown is observed

- **WHEN** the proposed revision is clearly slower than the base beyond the predeclared boundary for a guarded case
- **THEN** the guard fails and identifies the regressed case

#### Scenario: Host noise makes a comparison inconclusive

- **WHEN** valid repeated measurements do not distinguish a material slowdown from ordinary variation
- **THEN** the guard reports an inconclusive warning and the comparison does not fail as a performance regression

#### Scenario: The base implementation cannot be measured

- **WHEN** the base revision, compatible runtime, workload, or required case outcome is unavailable
- **THEN** the guard reports a measurement failure rather than silently treating the proposed revision as passing

### Requirement: Guard results support investigation and intentional trade-offs

The guard SHALL present per-case base and proposed measurements, relative change, variability or stability evidence, the decision boundary, revision identities, and the reason for a failed or inconclusive result. It SHALL preserve enough bounded diagnostic data to reproduce or investigate a failure without exposing application documents or credentials. Before the guard becomes a required check, repository administrators SHALL establish a reviewable merge-rule exception available only to designated maintainers, not pull-request authors acting alone. A known intentional slowdown SHALL require the performance cost and compensating reason to be recorded in the pull-request review and an authorized maintainer to use that exception; the measured guard result SHALL remain visible and failing. A checkbox, pull-request label, or self-declared bypass SHALL NOT suppress the guard. If the repository cannot provide that exception control, making the check required SHALL remain blocked until administrators resolve it.

#### Scenario: A regression fails CI

- **WHEN** a guarded case crosses the decision boundary with sufficient evidence
- **THEN** the check displays the measured change and enough run context to investigate it

#### Scenario: An intentional trade-off is accepted

- **WHEN** maintainers accept a documented performance cost for another benefit
- **THEN** a designated maintainer records the reason in review and uses the administrator-configured merge-rule exception, while the guard still reports the slowdown
