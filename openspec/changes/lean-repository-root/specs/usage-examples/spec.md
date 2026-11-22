## MODIFIED Requirements

### Requirement: Examples are complete real-library integrations

The repository SHALL provide a `docs/examples/` directory of complete programs integrating a published MongoDB-backed library or a published web framework with explicit MongoDB storage. Each SHALL use only the package's public API, without private imports. Each SHALL keep writes on PyMongo, route only supported reads through cached views, and close its manager and client on exit.

#### Scenario: A reader studies an example

- **WHEN** a reader opens an example
- **THEN** the example shows the whole integration in one file, from client and manager construction to shutdown, and imports nothing from a private `client_query_cache` module

#### Scenario: A reader studies a web application

- **WHEN** a reader opens the web-framework example
- **THEN** it demonstrates application-owned MongoDB storage rather than claiming the framework supplies a MongoDB backend

### Requirement: Examples run without project dependency changes

Each example SHALL declare its third-party libraries, with a minimum version, in inline script metadata inside the example file. From a repository checkout, `uv run docs/examples/<example>.py` SHALL provision those libraries ephemerally and run the example against the working-tree `client_query_cache`. Adding an example SHALL not add a runtime, optional, or development dependency to `pyproject.toml` or `uv.lock`. `docs/examples/README.md` SHALL list each example's run command.

#### Scenario: A contributor adds an example

- **WHEN** a contributor adds an example that needs a third-party library
- **THEN** `pyproject.toml` and `uv.lock` are unchanged, and `uv run docs/examples/<example>.py` runs it against the working-tree package

### Requirement: Examples are discoverable

The README SHALL link to the hosted examples catalogue. `docs/examples/README.md` SHALL list each example with the library or framework it integrates, its run command, and its MongoDB prerequisite. It SHALL describe current behavior only.

#### Scenario: A new user looks for integration guidance

- **WHEN** a new user reads the README
- **THEN** they find a link to runnable examples, and each listed example states how to run it
