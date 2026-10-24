## ADDED Requirements

### Requirement: Native unit tests and concurrency models fail validation

Native validation SHALL run the existing unit tests and bounded concurrency-model tests. Unit tests SHALL use production synchronization primitives, while models SHALL use their substituted synchronization primitives. A failing test or model SHALL fail validation.

#### Scenario: A publication race is detected

- **WHEN** a concurrency model observes an invalid publication or reuse ordering
- **THEN** native validation fails

#### Scenario: A unit test fails

- **WHEN** a native unit test observes incorrect behavior
- **THEN** native validation fails
