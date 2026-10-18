## ADDED Requirements

### Requirement: Bounded research cursor hits use shared publication

Research adapters SHALL serve exact positive-limit find hits from shared publication after complete consumption and authoritative admission. They SHALL retain owner selection on local absence and existing cursor behavior, bounds and failure fences. Public cursor caching remains outside this research contract.

#### Scenario: Another worker reads a sorted result

- **WHEN** one worker fully consumes and admits a bounded sorted find and another executes the same shape
- **THEN** the second worker serves a local shared hit without selecting through the owner

#### Scenario: A result is not completely consumed

- **WHEN** a cursor is closed before complete consumption
- **THEN** it publishes no partial result

### Requirement: Research result publication respects all writes

Every processed collection write SHALL invalidate its published find results, including writes with identities that cannot be canonicalized. Unrelated identity publications SHALL remain usable. Eviction, namespace reset, database availability and owner loss SHALL retain their existing safety behavior.

#### Scenario: A write changes sorted membership

- **WHEN** a processed write changes membership or ordering after a bounded result was published
- **THEN** the next local lookup cannot serve that publication

#### Scenario: A write crosses capture

- **WHEN** a write occurs after miss capture and before admission
- **THEN** the result is not published
