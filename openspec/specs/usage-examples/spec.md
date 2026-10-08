# usage-examples Specification

## Purpose

This capability gives new users complete, runnable integrations of the cache into real third-party libraries that already store data in MongoDB, and exposes public-interface and architecture friction that isolated tests cannot reveal.

## Requirements

### Requirement: Examples are complete real-library integrations

The repository SHALL provide a top-level `examples/` directory. Each example SHALL be a single complete program that integrates the cache into the storage layer of a real, published third-party library that already uses MongoDB. It SHALL use only the package's public API, and SHALL not import private `client_query_cache._*` modules. Each example SHALL keep writes on PyMongo and route only the library's supported reads through a cached view. It SHALL close its manager and client on exit.

#### Scenario: A reader studies an example

- **WHEN** a reader opens an example
- **THEN** the example shows the whole integration in one file, from client and manager construction to shutdown, and imports nothing from a private `client_query_cache` module

### Requirement: Examples run without project dependency changes

Each example SHALL declare its third-party libraries, with a minimum version, in inline script metadata inside the example file. From a repository checkout, `uv run examples/<example>.py` SHALL provision those libraries ephemerally and run the example against the working-tree `client_query_cache`. Adding an example SHALL not add a runtime, optional, or development dependency to `pyproject.toml` or `uv.lock`. `examples/README.md` SHALL list each example's run command.

#### Scenario: A contributor adds an example

- **WHEN** a contributor adds an example that needs a third-party library
- **THEN** `pyproject.toml` and `uv.lock` are unchanged, and `uv run examples/<example>.py` runs it against the working-tree package

### Requirement: Examples are self-contained

Each example SHALL read the MongoDB connection string from `MONGODB_URI`, defaulting to the replica set from the repository's `docker-compose.yaml`. It SHALL need no internet access beyond downloading packages; HTTP-client examples SHALL serve responses from a local in-process server.

#### Scenario: An example runs offline

- **WHEN** a user runs an example against a MongoDB 8.0+ replica set with no internet access and the packages already cached
- **THEN** it uses that replica set and any required local server without contacting an external service

### Requirement: Examples demonstrate cache behavior

Each example SHALL print public cache statistics proving repeated storage reads used the cache and evidence that a later storage write was observed through change-stream invalidation. HTTP-client examples SHALL include origin request counts.

#### Scenario: An example runs against a supported replica set

- **WHEN** a user runs an example against a supported replica set
- **THEN** it completes, prints cache hits for repeated storage reads, prints that a later write was observed through invalidation, and exits with status 0

### Requirement: Examples fail when expected cache behavior is absent

Each example SHALL exit with a non-zero status and a message naming the missing behavior when repeated storage reads produce no cache hits or invalidation is not observed within a bounded wait.

#### Scenario: Caching does not happen

- **WHEN** an example runs but its repeated storage reads produce no cache hits, or the invalidation is not observed within the bounded wait
- **THEN** the example exits with a non-zero status and a message naming the missing behavior

### Requirement: Examples are continuously verified

The pytest suite SHALL run every example as a subprocess with its documented `uv run` command against the disposable MongoDB replica set, and SHALL fail when an example exits with a non-zero status. The repository SHALL provide a `just examples` recipe that runs that verification. Static type checking SHALL cover every example with its third-party libraries available, in both the local lint workflow and CI.

#### Scenario: A library change breaks an example

- **WHEN** a change to `client_query_cache` makes an example fail at run time or type-check time
- **THEN** the pytest suite or type check fails in CI, naming the failing example

### Requirement: Examples are discoverable

The README SHALL link to the `examples/` directory. `examples/README.md` SHALL list each example with the third-party library it integrates, its run command, and its MongoDB prerequisite. It SHALL describe current behavior only.

#### Scenario: A new user looks for integration guidance

- **WHEN** a new user reads the README
- **THEN** they find a link to runnable examples, and each listed example states how to run it
