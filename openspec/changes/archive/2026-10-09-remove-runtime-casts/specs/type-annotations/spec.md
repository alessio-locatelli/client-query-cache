## ADDED Requirements

### Requirement: Static narrowing adds no recurring runtime calls

Repository Python code SHALL NOT call `typing.cast()` on recurring application paths or inside benchmark measurement loops. Casts MAY remain in tests, benchmark setup or reporting, and application setup or report assembly executed at most a few times per application lifetime.

#### Scenario: A cached read narrows a decoded value

- **WHEN** a collection or cursor consumes a cached value
- **THEN** static narrowing introduces no runtime function call

#### Scenario: Instrumentation observes repeated commands

- **WHEN** benchmark instrumentation observes a command during a measurement
- **THEN** it performs no `typing.cast()` call

#### Scenario: Setup narrows untyped configuration

- **WHEN** application configuration is loaded at most a few times per application lifetime
- **THEN** a cast is permitted at that boundary
