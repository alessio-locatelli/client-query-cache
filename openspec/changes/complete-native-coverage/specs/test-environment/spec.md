## ADDED Requirements

### Requirement: Native production coverage is complete

The native coverage command SHALL enforce 100% line and function coverage across production Rust source, including Python bindings. Reports SHALL combine native tests and tests exercising the instrumented extension. Ordinary production paths SHALL NOT be excluded to reach the threshold. Any uninstrumentable generated code or unreachable platform path exception SHALL have a concrete justification.

#### Scenario: A reachable native line is untested

- **WHEN** the native coverage report contains an unexecuted production line or function
- **THEN** the command identifies missing coverage and fails

#### Scenario: Python bindings are exercised

- **WHEN** Python tests call the instrumented extension
- **THEN** those executions contribute to the native report
