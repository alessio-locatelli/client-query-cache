# Spec Delta

## MODIFIED Requirements

### Requirement: Session-bound reads bypass caching

Session-bound reads SHALL bypass cache lookup and admission whether the session is supplied explicitly or inherited from a bound context. Explicit non-`None` sessions SHALL retain native precedence over bound contexts. Delegation SHALL preserve native session validation and errors. If effective-session resolution is unavailable or fails, reads SHALL bypass caching and execute natively.

#### Scenario: A session-bound read is requested

- **WHEN** a caller supplies a PyMongo session to a supported read
- **THEN** the facade delegates directly to PyMongo without a cache hit or admission

#### Scenario: A bound transaction repeats a warm query

- **WHEN** a caller binds a session, modifies a document in its transaction, and repeats a warm cached read with an omitted session or explicit `None`
- **THEN** the read executes in that transaction and observes its writes without a cache hit or admission

#### Scenario: A cold bound read returns session-scoped data

- **WHEN** a caller performs a cold supported read in a bound context
- **THEN** the facade executes the native read without admitting its result or negative result to the shared cache

#### Scenario: Native session restrictions apply after warming

- **WHEN** a warm supported read is repeated with an ended session, a different client's bound context, or a method that disallows sessions
- **THEN** the facade preserves the native validation error and its precedence over competing malformed arguments rather than returning the warm entry

#### Scenario: An explicit session overrides a bound context

- **WHEN** a caller supplies a non-`None` session while a different session is bound
- **THEN** the facade delegates using the supplied session and preserves PyMongo's validation behavior without a hit or admission

#### Scenario: A bound context exits

- **WHEN** a caller leaves a bound context and performs an otherwise eligible read in an unbound context
- **THEN** the read can use ordinary caching without inheriting the exited session

#### Scenario: Async execution contexts have distinct sessions

- **WHEN** one async execution context binds a session while another remains unbound
- **THEN** each read uses its own context, with only the bound read bypassing caching

#### Scenario: Effective-session capability is unavailable

- **GIVEN** the native client has no callable effective-session resolver
- **WHEN** a supported read is requested
- **THEN** the facade bypasses cache lookup and admission and executes the native read

#### Scenario: Effective-session inspection fails

- **WHEN** effective-session inspection raises an ordinary exception
- **THEN** the facade bypasses lookup and admission and lets the native read determine its result or error
