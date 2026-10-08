## MODIFIED Requirements

### Requirement: Examples are complete real-library integrations

The repository SHALL provide a top-level `examples/` directory of complete programs integrating a published MongoDB-backed library or a published web framework with explicit MongoDB storage. Each SHALL use only the package's public API, without private imports. Each SHALL keep writes on PyMongo, route only supported reads through cached views, and close its manager and client on exit.

#### Scenario: A reader studies an example

- **WHEN** a reader opens an example
- **THEN** the example shows the whole integration in one file, from client and manager construction to shutdown, and imports nothing from a private `client_query_cache` module

#### Scenario: A reader studies a web application

- **WHEN** a reader opens the web-framework example
- **THEN** it demonstrates application-owned MongoDB storage rather than claiming the framework supplies a MongoDB backend

## ADDED Requirements

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
