# Spec Delta

## MODIFIED Requirements

### Requirement: Incomplete results are not admitted

The facades SHALL admit only complete, bounded results of supported reads after successful consumption, guarded by the applicable ordinary or selective result generations and stream-availability generation captured before native execution.

#### Scenario: A caller abandons a cursor

- **WHEN** a caller partially consumes a cacheable-looking cursor
- **THEN** the facade does not admit its incomplete result to the cache

#### Scenario: The server exhausts before the caller consumes its batch

- **WHEN** the server cursor is exhausted but the caller leaves delivered batch documents unread
- **THEN** the facade does not admit the unread result

#### Scenario: Bounded to_list calls consume only a prefix

- **WHEN** a caller requests a prefix with `to_list(length=...)` and leaves documents unread
- **THEN** no entry is admitted until later calls consume the complete result

#### Scenario: An empty result is fully consumed

- **WHEN** a supported read successfully establishes that it has no documents
- **THEN** its empty result can be admitted under the same generation guards

#### Scenario: Execution fails after delivering documents

- **WHEN** a later batch raises a native error or cancellation interrupts execution
- **THEN** the incomplete result is not admitted and the error or cancellation propagates

#### Scenario: An invalidation or stream transition races consumption

- **WHEN** an invalidating write, namespace change, stream availability transition, or manager closure occurs between capture and full consumption
- **THEN** the result is not admitted under the obsolete capture

#### Scenario: An independent write races selective consumption

- **WHEN** a selective proof establishes that a processed write during complete consumption cannot affect the result
- **THEN** the write alone does not prevent admission, and all other admission checks still apply
