## ADDED Requirements

### Requirement: Shared fault registrations declare timing applicability

Shared fault registrations SHALL declare, for each case, whether detection, first safe readiness, first post-recovery hit and full rewarming apply. Missing declarations SHALL be configuration errors. Frozen earlier registrations SHALL remain unchanged.

#### Scenario: An older registration has only case names

- **WHEN** a fault phase is requested without timing applicability
- **THEN** planning fails before starting processes

### Requirement: Shared fault trials retain event-relative timings

Every registered case and repetition SHALL run against disposable MongoDB with the registered worker group. Detection SHALL start at injection; recovery timings SHALL start at the recovery action. All events SHALL use one monotonic clock. Inapplicable intervals SHALL be explicitly unavailable, never zero.

#### Scenario: A case has no recovery action

- **WHEN** malformed input or publication stress completes
- **THEN** the report retains its safety evidence and marks recovery intervals inapplicable

### Requirement: Shared fault outcomes require safety and readiness

Each trial SHALL check its scenario's safety and recovery invariants. Readiness SHALL require owner database availability, fresh upstream progress and worker eligibility. Rewarming SHALL require the hot set resident and, for a local-index path, published. Analysis SHALL report every duration per repetition and fail any safety violation, missing applicable timing or readiness above the registered bound.

#### Scenario: Recovery is fast but a stale capture is admitted

- **WHEN** a trial violates a safety invariant
- **THEN** its repetition and case fail regardless of measured durations

#### Scenario: A worker is eligible before the owner has fresh progress

- **WHEN** upstream progress is not fresh
- **THEN** the trial does not record safe readiness
