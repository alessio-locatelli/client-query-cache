# Spec Delta

## ADDED Requirements

### Requirement: The catalogue example runs under a multi-worker server

The catalogue example SHALL provide a documented command that serves the application through an HTTP server running a chosen number of worker processes. Each worker SHALL create its own client and manager in its application lifespan, and SHALL close the manager before the client when it shuts down. The pytest suite SHALL run this command with at least two workers.

#### Scenario: Two workers start and stop

- **WHEN** the verification launches the documented command with two workers, sends HTTP requests, and then stops the server
- **THEN** two distinct worker processes each report their own manager startup and closing the manager before the client, and the server exits successfully

#### Scenario: A reader selects caching for served workers

- **WHEN** a reader follows the guide to serve the catalogue with caching enabled
- **THEN** the guide states that every worker caches independently with its own change stream, and links to the deployment guide's multi-worker section
