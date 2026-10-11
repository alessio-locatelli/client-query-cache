# Spec Delta

## ADDED Requirements

### Requirement: Compact web integration demonstrates lifecycle and cache outcomes

A runnable FastAPI example SHALL expose a compact application section with one asyncio client and manager per lifespan, a cached read endpoint, a direct-write endpoint with a direct consistent read response, and a public metrics snapshot. Its self-check SHALL verify miss/hit observations and eventual cached convergence after a write without requiring a stale read to occur.

#### Scenario: A reader runs the compact example

- **WHEN** the example runs against a supported disposable replica set
- **THEN** it verifies request reuse, direct update responses, bounded eventual invalidation, and manager cleanup before client closure
- **AND** the guide shows the application separately from the executable self-check

### Requirement: Compact example verifies eligibility observations

The compact example's self-check SHALL verify public counter differences for session-bound reads, unsupported find options, nondeterministic aggregation, and oversized results. It SHALL exit unsuccessfully with a named failure if an expected observation is missing.

#### Scenario: A supported request intentionally bypasses the cache

- **WHEN** the self-check performs an ineligible request
- **THEN** it verifies the corresponding ordinary or oversized bypass counter while preserving normal PyMongo execution
