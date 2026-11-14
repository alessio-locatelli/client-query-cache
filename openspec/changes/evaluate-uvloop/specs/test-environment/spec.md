# Spec Delta

## ADDED Requirements

### Requirement: Async test-loop adoption uses end-to-end timing

Test-loop evaluation SHALL compare the same representative asynchronous tests in repeated interleaved fresh pytest runs. Evidence SHALL distinguish total process wall time from test setup, call and teardown durations, accounting for database startup and other overhead outside those phases. A faster benchmark alone SHALL NOT justify a test-default change; absent measurable test-duration improvement, the default loop SHALL remain unchanged.

#### Scenario: Faster calls do not shorten the test run

- **WHEN** uvloop improves test-call durations but total wall-clock changes remain within observed variation
- **THEN** the outcome is recorded as no demonstrated test-run improvement and no default change is made for performance

### Requirement: Selective loop coverage preserves standard asyncio

Any adopted uvloop test integration SHALL use `pytest_asyncio_loop_factories` without deprecated policies. Standard asyncio SHALL retain complete existing compatibility coverage. Additional loop coverage SHALL use a bounded representative subset rather than duplicate the suite. Missing support during an explicitly requested uvloop evaluation SHALL fail visibly. Unresolved loop-related defects SHALL be discussed before adoption.

#### Scenario: Only selected tests use an additional factory

- **WHEN** the ordinary suite is collected after integration
- **THEN** every existing test remains covered under standard asyncio and only the designated subset gains uvloop cases

#### Scenario: The requested loop cannot be loaded

- **WHEN** an explicit uvloop evaluation lacks its dependency or a supported build
- **THEN** the invocation reports that it cannot perform the requested evaluation instead of substituting asyncio or reporting skipped timing as success
