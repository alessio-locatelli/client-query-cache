## ADDED Requirements

### Requirement: Standalone startup diagnostics identify setup requirements

Sync and async stream startup failures confirmed by MongoDB as unsupported on standalone servers SHALL explain that caching requires a replica set or sharded cluster and link local setup guidance. The startup exception SHALL preserve the original PyMongo cause. Other startup failures SHALL NOT receive standalone-specific advice. Existing uncached fallback and recovery behavior SHALL be preserved.

#### Scenario: Standalone server rejects a change stream

- **WHEN** MongoDB returns error code 40573 during initial change-stream creation
- **THEN** the logged startup exception includes the prerequisite and setup link while retaining the server error as its cause and reads proceed uncached

#### Scenario: A different failure prevents startup

- **WHEN** authentication, server selection, or another command fails during startup
- **THEN** the startup exception retains its original cause without claiming that replication is disabled
