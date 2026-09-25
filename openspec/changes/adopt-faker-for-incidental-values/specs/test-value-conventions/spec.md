# Spec Delta

## Purpose

This capability defines when a test value must come from the `faker` fixture versus when a fixed value is acceptable, and what a fixed value that must stay exact requires so a future reader can tell the choice was deliberate.

## ADDED Requirements

### Requirement: Incidental test values use the `faker` fixture

A test value whose exact content is incidental to the behavior under test - the test would pass with any other value of the same shape and type - SHALL be produced by the `faker` fixture (directly or via a helper such as `make_fake_document`) rather than a hand-written literal, wherever the test can reach `faker`. A value generated once for a write and later relied on for a read, match, or assertion SHALL be generated exactly once and reused, not regenerated, so the write and the assertion stay consistent.

#### Scenario: A test inserts a document only to have some document present

- **WHEN** a test writes a document whose field values are never individually significant to the behavior under test
- **THEN** those field values come from `faker` rather than a hand-written literal

#### Scenario: A generated value is both written and later matched

- **WHEN** a test generates an incidental value, writes it, and later reads or matches against that same value
- **THEN** the test reuses the single generated value for both the write and the read instead of generating it twice

### Requirement: A test process without access to the `faker` fixture keeps fixed values

A test that cannot reach the `faker` fixture - because it runs generation-time code in a separate process, such as a subprocess-executed script - SHALL use a fixed or externally-threaded value instead of introducing process boundary-crossing plumbing solely to generate an incidental value.

#### Scenario: A value is needed inside a subprocess-executed test script

- **WHEN** a test constructs a value used only inside code executed in a separate process that has no access to the `faker` fixture
- **THEN** the test keeps a fixed value there rather than adding cross-process plumbing to generate one

### Requirement: A fixed value that must stay exact is self-explanatory

A hard-coded value or object whose exact content matters to the behavior under test - a boundary value, a value that must equal another literal elsewhere, or a value chosen to exercise specific behavior - SHALL be given a descriptive, self-documenting variable name, a module-level or fixture-scoped named constant, or a short inline comment explaining why that specific value was chosen over another. This requirement does not apply when the rationale for the value is already recorded in the file's git history; a contributor MAY leave such a value unrefactored and rely on that history for context.

#### Scenario: A test relies on a specific numeric or literal value

- **WHEN** a test's correctness depends on a specific hard-coded value rather than any value of the right shape
- **THEN** that value has a descriptive name, is a named constant or fixture, or carries a short inline comment explaining the choice, unless the file's git history already documents the rationale

#### Scenario: A significant value's rationale is already in git history

- **WHEN** a reviewer or contributor finds a significant hard-coded value with no local name, constant, or comment, but `git log`/`git blame` on that line already explains the choice
- **THEN** the value does not need to be refactored solely to add local documentation
