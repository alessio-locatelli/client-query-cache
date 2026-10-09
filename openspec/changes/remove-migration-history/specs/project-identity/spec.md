# Spec Delta

## MODIFIED Requirements

### Requirement: Public project identity uses one name

The repository, distribution, guidance, and diagnostics SHALL identify the project as `client-query-cache` at `https://github.com/alessio-locatelli/client-query-cache`.

#### Scenario: A user finds and installs the project

- **WHEN** a user follows current project guidance from the canonical repository
- **THEN** the project name and installation target are `client-query-cache`, and the guidance identifies PyMongo as the supported client library

#### Scenario: A startup error identifies the library

- **WHEN** synchronous or asynchronous cache startup reports an error that names the library
- **THEN** the diagnostic names it `client_query_cache`

## ADDED Requirements

### Requirement: The distribution provides the public import packages

The `client-query-cache` distribution SHALL provide `client_query_cache`, `client_query_cache.synchronous`, and `client_query_cache.asynchronous` as its public import paths.

#### Scenario: A user installs the distribution

- **WHEN** a user installs a built `client-query-cache` distribution in an isolated environment
- **THEN** documented synchronous and asynchronous public classes import through `client_query_cache`

## REMOVED Requirements

### Requirement: The public import package uses the new name

**Reason**: Its rename-migration duty is complete; "The distribution provides the public import packages" keeps the import contract.
**Migration**: None.
