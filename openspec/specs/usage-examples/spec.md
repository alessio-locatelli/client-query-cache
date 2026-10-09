# usage-examples Specification

## Purpose

This capability gives new users complete, runnable integrations of the cache into MongoDB-backed libraries and applications with explicit MongoDB storage, and exposes public-interface and architecture friction that isolated tests cannot reveal.

## Requirements

### Requirement: Examples are complete real-library integrations

The repository SHALL provide a top-level `examples/` directory of complete programs integrating a published MongoDB-backed library or a published web framework with explicit MongoDB storage. Each SHALL use only the package's public API, without private imports. Each SHALL keep writes on PyMongo, route only supported reads through cached views, and close its manager and client on exit.

#### Scenario: A reader studies an example

- **WHEN** a reader opens an example
- **THEN** the example shows the whole integration in one file, from client and manager construction to shutdown, and imports nothing from a private `client_query_cache` module

#### Scenario: A reader studies a web application

- **WHEN** a reader opens the web-framework example
- **THEN** it demonstrates application-owned MongoDB storage rather than claiming the framework supplies a MongoDB backend

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

The README SHALL link to the `examples/` directory. `examples/README.md` SHALL list each example with the library or framework it integrates, its run command, and its MongoDB prerequisite. It SHALL describe current behavior only.

#### Scenario: A new user looks for integration guidance

- **WHEN** a new user reads the README
- **THEN** they find a link to runnable examples, and each listed example states how to run it

### Requirement: A catalogue application demonstrates web lifecycle ownership

A runnable asyncio product-catalogue example SHALL create one client and manager per application lifespan, inject a repository into request handlers, and close the manager before its client. Its self-check SHALL drive application startup, requests, and shutdown without an external HTTP service and SHALL demonstrate cache reuse and eventual invalidation through the application.

#### Scenario: Requests share application resources

- **WHEN** the example handles repeated catalogue requests during one application lifespan
- **THEN** they use the same manager and client and report cache hits without constructing resources per request

#### Scenario: Application shutdown completes

- **WHEN** the self-check exits its application lifespan
- **THEN** manager cleanup completes before client closure

### Requirement: The catalogue separates cached content from freshness-critical reads

The catalogue repository SHALL cache product descriptions, perform writes on the raw collection, and read write responses directly with suitable session and concern settings. The guide SHALL explain that direct reads do not refresh other caches and that inventory commitments, payments, and immediate authorization decisions require their own database consistency controls.

#### Scenario: A product is updated

- **WHEN** a permitted caller updates a product through the example
- **THEN** the response obtains the updated document through PyMongo rather than relying on change-stream catch-up
- **AND** the self-check separately waits within a deadline for a subsequent cached request to observe invalidation

### Requirement: Catalogue queries use authenticated tenant context

Every catalogue read and write predicate SHALL include tenant identity supplied by a trusted application dependency. Client-supplied tenant selectors SHALL NOT replace that identity. The application SHALL reject requests without that dependency's authorization. The self-check MAY override it with explicitly labeled demonstration principals; cached documents SHALL NOT decide authorization.

#### Scenario: Two tenants share a product identifier

- **WHEN** two authorized demonstration principals request matching product identifiers or pages
- **THEN** each receives only its own tenant's documents, including on warmed-cache reads

#### Scenario: A caller attempts to select another tenant

- **WHEN** a request supplies another tenant identifier through request data
- **THEN** it cannot read or mutate that tenant's documents

#### Scenario: No application identity is available

- **WHEN** a request has no authorized principal
- **THEN** it fails before a catalogue lookup or write

### Requirement: Catalogue pagination demonstrates complete cursor consumption

The example SHALL show a deterministic sorted and limited product page, fully materialized before responding, and SHALL verify repeated-page cache reuse. The guide SHALL distinguish successful response delivery from cache admission and link to the canonical cursor guide for partial consumption and limit reuse.

#### Scenario: A page is repeated

- **WHEN** the same tenant requests the same page twice after stream activation
- **THEN** both responses have the expected ordered products and the second produces cache-hit evidence

### Requirement: Catalogue content caching is controlled by application configuration

The catalogue application SHALL select direct PyMongo or cached content reads through an application-owned deployment flag. Both modes SHALL return the expected tenant-scoped item and ordered page data. Writes and freshness-critical workflows SHALL remain direct in either mode. The example SHALL NOT require a package-level cache-enable option.

#### Scenario: Both storage selections are exercised

- **WHEN** the executable scenario requests items and pages with caching disabled and enabled
- **THEN** each mode returns the expected data for both demonstration tenants
- **AND** mutation responses use direct reads in each mode

### Requirement: Rollout selection does not change access checks

The catalogue SHALL apply its trusted identity dependency and authorization checks before storage access in both modes. Its rollout self-check SHALL verify missing identity, forbidden mutation, and tenant-selector tampering in each mode, including warmed-cache reads when enabled.

#### Scenario: Storage selection changes

- **WHEN** the self-check repeats authorized and unauthorized requests under each flag value
- **THEN** expected tenant isolation and access denials hold independently of the selection

### Requirement: The rollout guide states read consistency and availability boundaries

The canonical guide SHALL identify the direct-read concern and read preference chosen by the application, explain that eligible cache misses use majority read concern, and distinguish cache hits from server reads. It SHALL link the existing consistency guidance without promising identical freshness or availability across modes.

#### Scenario: A reader evaluates the deployment flag

- **WHEN** a reader follows the rollout guidance
- **THEN** they can identify each mode's read policy and why a cache hit, miss, or direct read has different execution and freshness behavior

### Requirement: Rollback retains stored data and closes application resources

The rollout scenario SHALL reuse one client and manager across requests within each application lifespan. It SHALL demonstrate disabled, enabled, then disabled operation over the same seeded data without resetting or migrating that data between modes. Each lifespan SHALL close its manager before its client and verify released cache resources.

#### Scenario: An enabled deployment is rolled back

- **WHEN** the enabled lifespan closes and a disabled lifespan starts over the same dataset
- **THEN** direct reads return the expected documents, including an authorized update from the enabled phase
- **AND** the closed manager reports no resident entries or bytes

### Requirement: Rollout observations use public snapshots

The scenario SHALL report public hit, miss, bypass, and resource snapshots at mode boundaries. It SHALL verify enabled reuse, a deliberate ineligible cached-view read, and unchanged cache counters during direct content reads. It SHALL distinguish direct reads from cache bypasses, and SHALL fail visibly when required evidence is missing.

#### Scenario: Cache and direct-read evidence is collected

- **WHEN** the self-check samples before and after each controlled operation
- **THEN** it demonstrates a miss, a subsequent hit, and an ordinary bypass when enabled
- **AND** direct reads leave cache outcome counters unchanged
- **AND** missing expected behavior causes a nonzero exit naming that behavior

### Requirement: Rollout operating policy stays with the application

The canonical rollout guide SHALL link the existing OpenTelemetry guide and rollback reference. It SHALL leave alert thresholds and rollout percentages to the application's operating policy.

#### Scenario: An operator adopts the example

- **WHEN** an operator reads the rollout guide extension
- **THEN** it points to the existing metrics integration and rollback contract without prescribing organization-specific thresholds or percentages
