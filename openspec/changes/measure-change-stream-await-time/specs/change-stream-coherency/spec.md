# Spec Delta

## ADDED Requirements

### Requirement: Managers configure change-stream await time explicitly

Synchronous and asynchronous managers SHALL use the same documented default `max_await_time_ms`, selected from retained measurements under the await-time decision rule. Each manager SHALL accept an optional public per-manager override and apply it to every database-scoped change stream it opens, including reopened streams. The override SHALL be a positive integer number of milliseconds within the supported wire-command range; invalid values SHALL fail at manager construction with a clear error. The library SHALL NOT read a process environment variable for this setting. The documentation SHALL explain that this is an upper bound on an idle `getMore` wait, that it does not guarantee a bound on event delivery or failure detection, and that callers must account for their PyMongo timeout settings.

#### Scenario: A manager uses the measured default

- **WHEN** a caller creates a manager without an await-time override
- **THEN** every stream it opens uses the documented measured default

#### Scenario: Managers require different await times

- **WHEN** a caller creates two managers with different valid overrides in one process
- **THEN** each manager uses its own value for both initial and reopened streams

#### Scenario: An invalid value is supplied

- **WHEN** a caller supplies zero, a negative value, a non-integer value, or a value outside the supported range
- **THEN** manager construction fails before opening a stream

#### Scenario: An environment variable is set

- **WHEN** a process environment variable names a different await time but the caller supplies no override
- **THEN** the manager uses its documented default
