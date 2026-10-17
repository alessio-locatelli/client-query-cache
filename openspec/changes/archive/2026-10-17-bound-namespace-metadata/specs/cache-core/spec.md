# Spec Delta

## ADDED Requirements

### Requirement: Tracked namespace state is bounded

Each cache core SHALL retain state for no more than its configured `max_namespaces` limit. The limit SHALL be a positive built-in integer. Requests for an untracked namespace at capacity SHALL bypass caching with the `namespace_capacity` reason while preserving native MongoDB behavior.

#### Scenario: Namespace capacity is exhausted

- **WHEN** a request first accesses a namespace while the cache core tracks `max_namespaces` other namespaces
- **THEN** it executes through MongoDB and records `namespace_capacity` without adding namespace state

#### Scenario: An invalid namespace limit is configured

- **WHEN** `max_namespaces` is zero, negative, or not a built-in integer
- **THEN** cache configuration raises `CacheConfigurationError` before cache use

### Requirement: Dropped namespaces release state safely

Processing a collection drop SHALL invalidate its entries and aliases, release its tracked namespace state, and make capacity available to another namespace. A capture made against the released state SHALL NOT admit after the name is reused.

#### Scenario: A dropped namespace releases capacity

- **WHEN** a tracked collection is dropped and another collection is requested afterward
- **THEN** the dropped state and its entries are reclaimed and the new collection can be tracked

#### Scenario: A delayed admission crosses drop and recreation

- **WHEN** an admission captured before a drop completes after the same collection name has been recreated
- **THEN** the old capture is rejected even if the new namespace has no cached entries

### Requirement: Process-local namespace metadata caches are bounded

Each process-local collection-metadata and unique-key-metadata cache SHALL retain no more than `max_namespaces` namespace entries and SHALL evict its oldest stored metadata when full.

#### Scenario: Metadata cache capacity is reached

- **WHEN** metadata is stored for more than `max_namespaces` namespaces
- **THEN** each metadata cache retains at most `max_namespaces` entries and keeps the most recently stored entries
