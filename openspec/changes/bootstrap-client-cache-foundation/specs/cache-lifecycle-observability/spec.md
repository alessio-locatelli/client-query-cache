## Purpose

Let applications observe whether caching is safely active and size it without
making cache health an invisible best-effort behavior.

## ADDED Requirements

### Requirement: Inspectable health and capacity
The cache manager SHALL expose its current lifecycle state, most recent
recoverable error, current retained bytes, configured limits, entry count, and
cache hit, miss, eviction, bypass, invalidation, and recovery counters.

#### Scenario: Application inspects a recovering cache
- **WHEN** a stream interruption places the manager in recovery
- **THEN** an inspection reports recovering state, the recovery error, and
  increasing bypass or recovery counters

### Requirement: Lifecycle and error reporting
The library SHALL emit structured standard-library log records for stream
startup, recovery attempts, cache clearing, and terminal startup errors. It
SHALL preserve the underlying MongoDB exception as the cause of an exposed
startup failure.

#### Scenario: Stream permission is denied
- **WHEN** stream startup fails with an authorization error
- **THEN** the startup error and corresponding log record identify the failure
  without exposing credentials or connection-string secrets

### Requirement: Capacity guidance
The published documentation SHALL explain that cache capacity is per process,
not per end user; identify the default byte and entry limits; and show how to
size the cache from observed BSON result sizes, hit rate, process memory limit,
and the number of cache managers in a process.

#### Scenario: Application uses default capacity
- **WHEN** an application constructs the default in-memory backend
- **THEN** its documentation and inspection output identify the 64 MiB budget
  and 1 MiB maximum entry size
