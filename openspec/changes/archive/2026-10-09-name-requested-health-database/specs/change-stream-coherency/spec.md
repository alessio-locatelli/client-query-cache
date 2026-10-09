# Spec Delta

## ADDED Requirements

### Requirement: Health observations echo the requested database name

A database health observation SHALL identify its database as `requested_database_name`, holding exactly the name the caller requested, without validating that name.

#### Scenario: A caller inspects an empty database name

- **WHEN** a caller requests health for an empty database name on an open manager
- **THEN** the observation reports that no stream has started and its `requested_database_name` is the empty string

#### Scenario: A caller inspects a name after closure

- **WHEN** a caller requests health for any name after the manager closes
- **THEN** the observation reports closed management and echoes that name
