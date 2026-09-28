# Test Value Conventions Specification

## Purpose

This capability defines when a test value must come from the `faker` fixture versus when a fixed value is acceptable, and what a fixed value that must stay exact requires so a future reader can tell the choice was deliberate.

## Requirements

### Requirement: Incidental values come from Faker

Tests SHALL use the `faker` fixture or a helper for incidental values wherever the fixture is available.

#### Scenario: A test inserts a document only to have some document present

- **WHEN** a test writes a document whose field values are never individually significant to the behavior under test
- **THEN** those field values come from `faker` rather than a hand-written literal

### Requirement: Generated values are reused when matched later

A generated value used for both a write and later match or assertion SHALL be generated once and reused.

#### Scenario: A generated value is both written and later matched

- **WHEN** a test generates an incidental value, writes it, and later reads or matches against that same value
- **THEN** the test reuses the single generated value for both the write and the read instead of generating it twice

### Requirement: A test process without access to the `faker` fixture keeps fixed values

A test that cannot reach the `faker` fixture - because it runs generation-time code in a separate process, such as a subprocess-executed script - SHALL use a fixed or externally-threaded value instead of introducing process boundary-crossing plumbing solely to generate an incidental value.

#### Scenario: A value is needed inside a subprocess-executed test script

- **WHEN** a test constructs a value used only inside code executed in a separate process that has no access to the `faker` fixture
- **THEN** the test keeps a fixed value there rather than adding cross-process plumbing to generate one

### Requirement: Exact test values explain their purpose

A behavior-significant fixed value SHALL have a descriptive name, named constant, or short explanatory comment unless its rationale is recorded in the file history.

#### Scenario: A test relies on a specific numeric or literal value

- **WHEN** a test's correctness depends on a specific hard-coded value rather than any value of the right shape
- **THEN** that value has a descriptive name, is a named constant or fixture, or carries a short inline comment explaining the choice, unless the file's git history already documents the rationale

#### Scenario: A significant value's rationale is already in git history

- **WHEN** a reviewer or contributor finds a significant hard-coded value with no local name, constant, or comment, but `git log`/`git blame` on that line already explains the choice
- **THEN** the value does not need to be refactored solely to add local documentation
