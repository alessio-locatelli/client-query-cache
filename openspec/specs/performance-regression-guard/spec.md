# performance-regression-guard Specification

## Purpose

This capability detects clear, material slowdowns in shipped cache hot paths introduced by a pull request using comparable measurements of the base and proposed revisions.

## Requirements

### Requirement: Relevant pull requests run the cache hot-path guard

CI SHALL run a bounded sync and asyncio cache-hit, admission, and invalidation guard for changes affecting Python code, runtime dependencies, or guard inputs.

#### Scenario: A Python change affects a shared cache path

- **WHEN** a pull request changes Python code that may affect cached reads or invalidation
- **THEN** CI measures the guarded paths for the base and proposed revisions and reports a guard result

#### Scenario: A case never exercises its claimed cache outcome

- **WHEN** a timed case does not produce its required hit, admission, or invalidation outcome
- **THEN** its measurement is rejected rather than compared as valid performance evidence

### Requirement: Unaffected pull requests keep a stable guard status

CI SHALL provide a stable guard status for pull requests that do not affect its inputs.

#### Scenario: A documentation-only change is proposed

- **WHEN** a pull request changes no Python code, Python runtime dependency, or guard input
- **THEN** the guard reports a successful, explicit skip without running timed workloads

### Requirement: Guard decisions compare matched base and proposed runs

Each case SHALL compare base and proposed revisions on the same runner with matched data, warmup, counterbalanced repetitions, and a predeclared 30% slowdown boundary.

#### Scenario: A stable material slowdown is observed

- **WHEN** the proposed revision is clearly slower than the base beyond the predeclared boundary for a guarded case
- **THEN** the guard fails and identifies the regressed case

### Requirement: Noisy guard comparisons are inconclusive

The guard SHALL use a predeclared stability rule so host noise does not turn an uncertain comparison into a performance failure.

#### Scenario: Host noise makes a comparison inconclusive

- **WHEN** valid repeated measurements do not distinguish a material slowdown from ordinary variation
- **THEN** the guard reports an inconclusive warning and the comparison does not fail as a performance regression

### Requirement: Unmeasurable base revisions are reported

The guard SHALL report when the base revision cannot be measured rather than manufacture a relative result.

#### Scenario: The base implementation cannot be measured

- **WHEN** the base revision, compatible runtime, workload, or required case outcome is unavailable
- **THEN** the guard reports a measurement failure rather than silently treating the proposed revision as passing

### Requirement: Guard reports retain bounded decision evidence

The guard SHALL report per-case measurements, relative change, stability evidence, decision boundary, revision identities, workload definition, and failure reason without application data or credentials.

#### Scenario: A regression fails CI

- **WHEN** a guarded case crosses the decision boundary with sufficient evidence
- **THEN** the check displays the measured change and enough run context to investigate it

### Requirement: Intentional slowdowns require maintainer review

An intentional slowdown SHALL retain a failing guard result and require a documented trade-off plus a designated maintainer merge-rule exception.

#### Scenario: An intentional trade-off is accepted

- **WHEN** maintainers accept a documented performance cost for another benefit
- **THEN** a designated maintainer records the reason in review and uses the administrator-configured merge-rule exception, while the guard still reports the slowdown

### Requirement: Required guard status depends on a controlled exception

Before the guard becomes required, administrators SHALL provide a reviewable merge-rule exception restricted to designated maintainers; without that control, required status remains blocked.

#### Scenario: A pull-request author attempts to bypass a failure

- **WHEN** a guard failure is labeled, checked off, or otherwise self-declared acceptable by its author
- **THEN** the failing result remains visible and only a designated maintainer can use the reviewable exception after the trade-off is recorded
