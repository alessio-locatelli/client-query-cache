## MODIFIED Requirements

### Requirement: Guard reports retain bounded decision evidence

The guard SHALL report per-case measurements, relative change, stability evidence, decision boundary, revision identities, workload definition, and failure reason without application data or credentials. Completed measurements rejected during evaluation SHALL remain in the artifact, and CI SHALL display rejection reasons in its step log and job summary.

#### Scenario: A regression fails CI

- **WHEN** a guarded case crosses the decision boundary with sufficient evidence
- **THEN** the check displays the measured change and enough run context to investigate it

#### Scenario: A completed block is too short

- **WHEN** evaluation rejects a completed timing block below the minimum duration
- **THEN** the artifact retains both timing arrays and the displayed reason identifies the revision side, block number, duration, and required minimum
