# Spec Delta

## MODIFIED Requirements

### Requirement: Public documentation describes only implemented behavior

The README and public guides SHALL collectively identify the audience, supported Python and MongoDB topology, installation, stable quick starts, lifecycle, consistency, recovery, capacity, security boundaries, and non-goals. Commands and examples SHALL be verified against the implemented public API.

#### Scenario: A new user follows the quick start

- **WHEN** a user follows the documented supported quick start
- **THEN** it uses only published public APIs and states the replica-set or sharded-cluster prerequisite for change streams

### Requirement: Operations guidance exposes trade-offs and limits

Public guides SHALL cover system requirements, capacity, retry/error handling, observability, security, recovery, and performance, with versioned benchmark evidence and no promise of instantaneous or universally beneficial coherence. Practical deployment guidance SHALL be hosted; internal architecture, engineering decisions, and research SHALL remain repository-only development documentation.

#### Scenario: An operator evaluates a workload

- **WHEN** an operator reads the workload guidance
- **THEN** it can identify the read/write, topology, document-size, and stream-health factors that determine whether the cache is appropriate

#### Scenario: An operator plans a deployment

- **WHEN** an operator reads the public operations section
- **THEN** it can determine manager and client ownership, process-local memory and stream costs, security limits, recovery behavior, and monitoring options without reading internal design or research documents

### Requirement: Documentation navigation supports common reader tasks

The site SHALL provide a landing page and populated sections for getting started, usage, benchmarks, examples, reference, and operations. It SHALL support full-text search, mobile navigation, keyboard access to navigation and search, light/dark appearance selection, readable code blocks, and heading permalinks.

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

Public API, operations, and performance guides SHALL remain canonical Markdown sources readable in the repository; the site SHALL render those sources without separately maintained guide copies. Each detailed topic SHALL have one canonical source, with other entry points using links or build-time inclusion. Example instructions and executable code SHALL likewise be reused from canonical repository files.

#### Scenario: A contributor updates a canonical guide

- **WHEN** a contributor changes an API, operations, or performance Markdown guide
- **THEN** the next site build renders that source without requiring an update to a duplicate guide

#### Scenario: A contributor updates canonical content

- **WHEN** a contributor changes canonical example instructions or executable example code used by a page
- **THEN** the next site build renders that revision without requiring the contributor to edit a duplicate copy

### Requirement: Published documentation links resolve under the project subpath

Published page links, heading links, and bundled assets SHALL resolve under the hosting project's URL subpath. Previously published public guide pages and their documented headings SHALL continue to reach relevant hosted guidance after moves or splits.

#### Scenario: A reader follows related guidance

- **WHEN** a reader follows an API-to-operations heading link on the hosted site
- **THEN** the destination opens the corresponding rendered guide and heading under the project URL subpath

#### Scenario: A reader opens a bundled asset

- **WHEN** a reader opens a guide containing a bundled asset on the hosted site
- **THEN** the asset resolves under the hosting project's URL subpath

#### Scenario: A reader follows an existing bookmark

- **WHEN** a reader opens a previously published API, architecture-and-operations, or performance page URL or documented heading URL
- **THEN** the reader reaches the corresponding public content on the site after the restructure, including a public explanation when a former heading described internal design

### Requirement: Repository references resolve to their source destinations

References to contributor instructions, explicit example-source links, and versioned benchmark evidence SHALL resolve to their repository destinations.

#### Scenario: A reader follows benchmark evidence

- **WHEN** a reader follows a benchmark evidence or explicitly identified example-source link from the hosted site
- **THEN** the destination is the intended repository file or directory rather than an absent site page

## ADDED Requirements

### Requirement: Documentation separates public and development sources

Public and development documentation SHALL occupy distinct, descriptively named subdirectories of `docs/`.

#### Scenario: A contributor locates documentation sources

- **WHEN** a contributor opens `docs/`
- **THEN** descriptive subdirectories distinguish published user guidance from repository-only development documentation

### Requirement: Documentation input selection follows canonical content

Documentation validation and publication SHALL select all canonical site inputs, including example prose and code. Development-only documentation SHALL NOT select site builds or publication. Public-guide-only Markdown SHALL NOT select Python package or database tests. Existing strict-build failures and least-privilege publication boundaries SHALL remain effective.

#### Scenario: An example included in the site changes

- **WHEN** a change modifies example instructions or executable source rendered on the site
- **THEN** documentation validation selects a build and the publication workflow recognizes the changed input on the default branch

#### Scenario: A maintainer note changes

- **WHEN** a change modifies only repository-only development Markdown
- **THEN** ordinary documentation formatting and link checks remain applicable, but the change does not select a site build or publication

### Requirement: README provides a concise entry point

The README SHALL provide a concise product introduction, essential caching prerequisites, installation, an asynchronous-invalidation caveat, and direct hosted getting-started and detailed-guide links. Detailed tutorials, configuration, and benchmark analysis SHALL have canonical guide destinations rather than parallel README sections.

#### Scenario: A reader starts from the repository or package page

- **WHEN** a reader opens the README
- **THEN** they can identify the library's purpose, install it, understand essential caching prerequisites and consistency limits, and reach the hosted tutorial without reading a complete API or operations guide

### Requirement: Hosted learning journeys are self-contained

Readers SHALL proceed from installation through synchronous or asyncio usage, workload evaluation, integrations, and API details on rendered site pages. Hosted tutorials and examples SHALL NOT substitute GitHub READMEs for guidance. Examples SHALL show prerequisites, commands, integration explanations, and relevant code. External source, checkout, upstream-documentation, and benchmark-evidence links SHALL be explicitly identified.

#### Scenario: A reader learns the library on the site

- **WHEN** a reader follows getting-started and usage navigation from the landing page
- **THEN** installation and complete synchronous and asyncio quick starts render on the site, with manager cleanup, raw writes, list-returning reads, and eventual invalidation explained

#### Scenario: A reader studies an integration

- **WHEN** a reader opens the site's examples section
- **THEN** delivered examples have hosted prerequisites, run commands, explanations, and relevant integration code, while optional links to source files are clearly identified
