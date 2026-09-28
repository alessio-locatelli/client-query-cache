# Spec Delta

## ADDED Requirements

### Requirement: Managers use one measured await-time default

Synchronous and asynchronous managers SHALL use the same documented default `max_await_time_ms` selected from retained measurements.

#### Scenario: A manager uses the measured default

- **WHEN** a caller creates a manager without an await-time override
- **THEN** every stream it opens uses the documented measured default

### Requirement: Managers apply a validated await-time override

Each manager SHALL accept a positive integer millisecond override in the supported wire-command range and apply it to opened and reopened streams. Boolean values SHALL be rejected as invalid, along with other invalid values, at manager construction.

#### Scenario: Managers require different await times

- **WHEN** a caller creates two managers with different valid overrides in one process
- **THEN** each manager uses its own value for both initial and reopened streams

#### Scenario: An invalid value is supplied

- **WHEN** a caller supplies a boolean, zero, a negative value, a non-integer value, or a value outside the supported range
- **THEN** manager construction fails before opening a stream

### Requirement: Await time is not configured from the environment

The library SHALL NOT read a process environment variable for `max_await_time_ms`.

#### Scenario: An environment variable is set

- **WHEN** a process environment variable names a different await time but the caller supplies no override
- **THEN** the manager uses its documented default

### Requirement: Await-time guidance explains timeout limits

Public guidance SHALL describe `max_await_time_ms` as an upper bound on an idle `getMore` wait, not a guaranteed bound on event delivery or failure detection, and explain its interaction with PyMongo timeout settings.

#### Scenario: A caller chooses an await-time override

- **WHEN** the caller reads the manager argument documentation
- **THEN** it distinguishes idle `getMore` waiting from delivery and failure-detection latency and points out the relevant PyMongo timeout settings
