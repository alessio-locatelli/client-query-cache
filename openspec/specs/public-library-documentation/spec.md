# public-library-documentation Specification

## Purpose

This capability gives public users accurate, evidence-backed documentation for the implemented MongoDB client-side cache and its operating boundaries.

## Requirements

### Requirement: Public documentation describes only implemented behavior

The README and public guides SHALL identify the target audience, supported Python and MongoDB topology, installation, stable quick starts, lifecycle, cache consistency model, recovery behavior, capacity limits, security boundaries, and explicit non-goals. Commands and examples SHALL be verified against the implemented public API.

#### Scenario: A new user follows the quick start

- **WHEN** a user follows the documented supported quick start
- **THEN** it uses only published public APIs and states the replica-set or sharded-cluster prerequisite for change streams

### Requirement: Operations guidance exposes trade-offs and limits

The documentation SHALL provide system requirements, capacity estimation, high-level and low-level architecture, retry/error handling, observability, and performance guidance. It SHALL link versioned benchmark evidence for performance claims and SHALL not promise instantaneous or universally beneficial coherence.

#### Scenario: An operator evaluates a workload

- **WHEN** an operator reads the workload guidance
- **THEN** it can identify the read/write, topology, document-size, and stream-health factors that determine whether the cache is appropriate

### Requirement: Public documentation is available as a free hosted site

The library SHALL provide a public HTTPS documentation site that readers can use without an account. Hosting SHALL require no paid plan or custom domain for the project's public repository. The README and package metadata SHALL identify the documentation URL. The site SHALL identify its content as current default-branch documentation rather than promising correspondence to every published library version.

#### Scenario: A reader discovers the documentation

- **WHEN** a reader follows the documentation link from the README or package metadata
- **THEN** the reader can open the public site without authentication and identify which development state it documents

### Requirement: Documentation navigation supports common reader tasks

The site SHALL provide a landing page, installation and quick-start access, API reference, architecture and operations guidance, performance guidance, and links to runnable examples. It SHALL support full-text search, mobile navigation, keyboard access to navigation and search, light/dark appearance selection, readable code blocks, and heading permalinks.

#### Scenario: A reader locates an API option

- **WHEN** a reader searches for `max_await_time_ms`
- **THEN** the search returns relevant API guidance and allows the reader to open that section

#### Scenario: A reader uses a small screen or keyboard

- **WHEN** a reader navigates on a mobile viewport or uses only a keyboard
- **THEN** the reader can open navigation, reach the API guide, use search, and read code without page-wide horizontal overflow

#### Scenario: A reader selects an appearance

- **WHEN** a reader switches between light and dark appearances
- **THEN** text, links, and code remain legible in the selected appearance

### Requirement: Published guides preserve canonical sources and working links

Existing API, operations, and performance Markdown guides SHALL remain canonical and readable in the repository. The site SHALL render those sources without maintaining duplicate guide copies.

#### Scenario: A contributor updates a canonical guide

- **WHEN** a contributor changes an API, operations, or performance Markdown guide
- **THEN** the next site build renders that source without requiring an update to a duplicate guide

### Requirement: Published documentation links resolve under the project subpath

Published page links, heading links, and bundled assets SHALL resolve under the hosting project's URL subpath.

#### Scenario: A reader follows related guidance

- **WHEN** a reader follows an API-to-operations heading link on the hosted site
- **THEN** the destination opens the corresponding rendered guide and heading under the project URL subpath

#### Scenario: A reader opens a bundled asset

- **WHEN** a reader opens a guide containing a bundled asset on the hosted site
- **THEN** the asset resolves under the hosting project's URL subpath

### Requirement: Repository references resolve to their source destinations

References to repository-only examples, contributor instructions, and versioned benchmark evidence SHALL resolve to their repository destinations.

#### Scenario: A reader follows benchmark evidence

- **WHEN** a reader follows a benchmark evidence or runnable-example link from the hosted site
- **THEN** the destination is the intended repository file or directory rather than an absent site page

### Requirement: Development material stays outside hosted content

Maintainer and research documents SHALL remain repository references and SHALL be excluded from hosted content and search. Relevant technical guides MAY link to them contextually on GitHub. OpenSpec planning artifacts and library source trees SHALL not be published as site content.

#### Scenario: A reader searches for maintainer notes

- **WHEN** a reader searches the hosted site for a development-only research or publishing-setup document
- **THEN** that document is absent from the search index and published content

#### Scenario: A contributor builds the site

- **WHEN** a contributor builds the hosted documentation
- **THEN** OpenSpec planning artifacts and library source trees are absent from the published content

### Requirement: Contributors can preview and build documentation reproducibly

Contributors SHALL have one documented command for local live preview and one for a clean strict static build using committed dependency versions. Neither operation SHALL require MongoDB, Docker, hosting credentials, or changes to runtime dependencies. Generated site output SHALL remain untracked.

#### Scenario: A contributor previews a guide

- **WHEN** a contributor starts the documented preview command and edits a guide
- **THEN** the guide can be inspected locally with the site's navigation and theme

#### Scenario: A contributor builds documentation locally

- **WHEN** a contributor runs the documented clean strict build
- **THEN** it uses committed dependency versions without requiring MongoDB, Docker, hosting credentials, or changes to runtime dependencies, and its output remains untracked

### Requirement: Documentation validation reports invalid inputs

Invalid configuration, missing page targets, and missing heading targets SHALL produce visible failures in the strict build. The existing Lychee quality gate SHALL reject missing authored asset targets.

#### Scenario: Documentation configuration is invalid

- **WHEN** a contributor builds documentation with invalid configuration
- **THEN** the strict build exits unsuccessfully with a visible diagnostic

#### Scenario: A documentation link is broken

- **WHEN** a contributor builds documentation containing a missing local page or heading target
- **THEN** the strict build exits unsuccessfully with a visible diagnostic

#### Scenario: An authored asset is missing

- **WHEN** a contributor runs the existing Lychee quality gate against a guide containing a missing local asset
- **THEN** the gate exits unsuccessfully with a visible missing-file diagnostic
