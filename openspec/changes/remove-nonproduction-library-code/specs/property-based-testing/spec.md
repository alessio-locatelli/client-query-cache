# Spec Delta

## MODIFIED Requirements

### Requirement: Cache admission, lookup, write, and clear ordering has stateful coverage

The repository SHALL exercise the production native cache core's identity and namespace admission, lookup, write, and clear operations through a Hypothesis rule-based state machine asserting that a lookup never returns a value staler than the most recent successful write or clear affecting its key, and that admission bookkeeping accounts for exactly the resident entries. The state machine SHALL hold only expected values, not a second admission, eviction, or invalidation algorithm.

#### Scenario: A generated operation sequence runs against the cache core

- **WHEN** Hypothesis generates a sequence of admission, lookup, write, and clear operations over a bounded identity/namespace alphabet
- **THEN** every lookup result reflects the most recent write or clear affecting its key, and admission bookkeeping accounts for exactly the resident entries

## REMOVED Requirements

### Requirement: Weighted LRU budget and ordering invariants have stateful coverage

**Reason**: The Python `WeightedLru` was part of the retained non-production cache engine. Production eviction and budget enforcement belong to the native core.

**Migration**: Budget bounds and stale-generation freshness are asserted on the production core through its snapshots and generated operation schedules, and eviction order through its contract tests, under the cache-core and process-local-cache-evaluation requirements.
