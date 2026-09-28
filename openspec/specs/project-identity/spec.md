# project-identity Specification

## Purpose

This capability keeps the project's public repository, installable distribution, Python imports, and user guidance aligned under one identifiable name.

## Requirements

### Requirement: Public project identity uses one name

The repository, distribution, guidance, and diagnostics SHALL identify the project as `client-query-cache` at `https://github.com/alessio-locatelli/client-query-cache`.

#### Scenario: A user finds and installs the project

- **WHEN** a user follows current project guidance from the canonical repository
- **THEN** the project name and installation target are `client-query-cache`, and the guidance identifies PyMongo as the supported client library

#### Scenario: A startup error identifies the library

- **WHEN** synchronous or asynchronous cache startup reports an error that names the library
- **THEN** the diagnostic uses the new identity rather than `mongo_client_cache`

### Requirement: Public positioning describes independent PyMongo caching

Public guidance SHALL describe client-side caching for PyMongo kept coherent by MongoDB change streams without implying MongoDB produced or endorsed the project.

#### Scenario: A user reads the project description

- **WHEN** public guidance describes the library's purpose
- **THEN** it explains the PyMongo cache and change-stream coherency without claiming MongoDB authorship or endorsement

### Requirement: The public import package uses the new name

The `client-query-cache` distribution SHALL provide `client_query_cache`, `client_query_cache.synchronous`, and `client_query_cache.asynchronous` as its public import paths. The project SHALL document the rename from `mongo-client-cache` and `mongo_client_cache` as a breaking migration, with an explicit dependency and import update for existing users. The old import path SHALL NOT be retained as a compatibility alias.

#### Scenario: A user installs the renamed distribution

- **WHEN** a user installs a built `client-query-cache` distribution in an isolated environment
- **THEN** documented synchronous and asynchronous public classes import through `client_query_cache`

#### Scenario: A current user migrates

- **WHEN** a user follows the migration guidance for the rename
- **THEN** they can identify both the new dependency name and the new import paths, including that the former import path is unavailable
