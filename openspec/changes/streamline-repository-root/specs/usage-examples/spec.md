# Usage examples delta

## MODIFIED Requirements

### Requirement: Examples are self-contained

Each example SHALL read the MongoDB connection string from `MONGODB_URI`, defaulting to the local replica set described in `docs/user/getting-started/installation.md`. It SHALL need no internet access beyond downloading packages. HTTP-client examples SHALL serve responses from a local in-process server.

#### Scenario: An example runs offline

- **WHEN** a user runs an example against a MongoDB 8.0+ replica set with no internet access and the packages already cached
- **THEN** it uses that replica set and any required local server without contacting an external service
