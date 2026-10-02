# Spec Delta

## MODIFIED Requirements

### Requirement: Public documentation describes only implemented behavior

The README and public guides SHALL collectively identify the target audience, supported Python and MongoDB topology, installation, stable quick starts, lifecycle, cache consistency model, recovery behavior, capacity limits, security boundaries, and explicit non-goals. The README SHALL provide a concise product introduction, essential caching prerequisites, installation, an asynchronous-invalidation caveat, and direct links to hosted getting-started and detailed guidance. Detailed tutorials, configuration, and benchmark analysis SHALL have canonical guide destinations rather than parallel README sections. Commands and examples SHALL be verified against the implemented public API.

#### Scenario: A new user follows the quick start

- **WHEN** a user follows the documented supported quick start
- **THEN** it uses only published public APIs and states the replica-set or sharded-cluster prerequisite for change streams

#### Scenario: A reader starts from the repository or package page

- **WHEN** a reader opens the README
- **THEN** they can identify the library's purpose, install it, understand essential caching prerequisites and consistency limits, and reach the hosted tutorial without reading a complete API or operations guide

### Requirement: Operations guidance exposes trade-offs and limits

Public documentation SHALL provide system requirements, capacity estimation, retry/error handling, observability, security boundaries, recovery behavior, and performance guidance. It SHALL link versioned benchmark evidence for performance claims and SHALL not promise instantaneous or universally beneficial coherence. Practical deployment guidance SHALL remain available on the site; internal high-level and low-level architecture, engineering decisions, and research SHALL be organized as repository-only development documentation.

#### Scenario: An operator evaluates a workload

- **WHEN** an operator reads the workload guidance
- **THEN** it can identify the read/write, topology, document-size, and stream-health factors that determine whether the cache is appropriate

#### Scenario: An operator plans a deployment

- **WHEN** an operator reads the public operations section
- **THEN** it can determine manager and client ownership, process-local memory and stream costs, security limits, recovery behavior, and monitoring options without reading internal design or research documents

### Requirement: Documentation navigation supports common reader tasks

The site SHALL provide a landing page and clearly grouped, populated sections for getting started, usage, benchmarks, examples, reference, and operations. Readers SHALL be able to proceed from installation through synchronous or asyncio usage, workload evaluation, integration examples, and API details using rendered site pages. Getting-started and examples navigation SHALL NOT use GitHub README pages as substitutes for hosted guidance. Example guidance SHALL provide prerequisites, run commands, integration explanations, and relevant code on the site; explicit source, checkout, upstream-documentation, and benchmark-evidence links can lead outside the site. The site SHALL support full-text search, mobile navigation, keyboard access to navigation and search, light/dark appearance selection, readable code blocks, and heading permalinks.

#### Scenario: A reader locates an API option

- **WHEN** a reader searches for `max_await_time_ms`
- **THEN** the search returns relevant API guidance and allows the reader to open that section

#### Scenario: A reader uses a small screen or keyboard

- **WHEN** a reader navigates on a mobile viewport or uses only a keyboard
- **THEN** the reader can open navigation, reach the API guide, use search, and read code without page-wide horizontal overflow

#### Scenario: A reader selects an appearance

- **WHEN** a reader switches between light and dark appearances
- **THEN** text, links, and code remain legible in the selected appearance

#### Scenario: A reader learns the library on the site

- **WHEN** a reader follows getting-started and usage navigation from the landing page
- **THEN** installation and complete synchronous and asyncio quick starts render on the site, with manager cleanup, raw writes, list-returning reads, and eventual invalidation explained

#### Scenario: A reader studies an integration

- **WHEN** a reader opens the site's examples section
- **THEN** delivered examples have hosted prerequisites, run commands, explanations, and relevant integration code, while optional links to source files are clearly identified

### Requirement: Published guides preserve canonical sources and working links

Public and development documentation SHALL occupy distinct, descriptively named subdirectories of `docs/`. Public API, operations, and performance guides SHALL remain canonical Markdown sources accessible in the repository; the site SHALL render those sources without separately maintained guide copies. Each detailed topic SHALL have one canonical source, with other entry points using links or build-time inclusion. Example instructions and executable code SHALL likewise be reused from canonical repository files. Published page links, heading links, and bundled assets SHALL resolve under the hosting project's URL subpath. Previously published public guide pages and their documented headings SHALL continue to reach relevant hosted guidance after moves or splits. References to contributor instructions, explicit example-source links, and versioned benchmark evidence SHALL resolve to their repository destinations. Maintainer and research documents SHALL remain repository references and SHALL be excluded from hosted content and search. Relevant technical guides MAY link to them contextually on GitHub. OpenSpec planning artifacts and library source trees SHALL not be published as site content.

#### Scenario: A reader follows related guidance

- **WHEN** a reader follows an API-to-operations heading link on the hosted site
- **THEN** the destination opens the corresponding rendered guide and heading under the project URL subpath

#### Scenario: A reader follows benchmark evidence

- **WHEN** a reader follows a benchmark evidence or explicitly identified example-source link from the hosted site
- **THEN** the destination is the intended repository file or directory rather than an absent site page

#### Scenario: A contributor updates canonical content

- **WHEN** a contributor changes canonical example instructions or executable example code used by a page
- **THEN** the next site build renders that revision without requiring the contributor to edit a duplicate copy

#### Scenario: A reader follows an existing bookmark

- **WHEN** a reader opens a previously published API, architecture-and-operations, or performance page URL or documented heading URL
- **THEN** the reader reaches the corresponding public content on the site after the restructure, including a public explanation when a former heading described internal design

#### Scenario: A reader searches for maintainer notes

- **WHEN** a reader searches the hosted site for a development-only research or publishing-setup document
- **THEN** that document is absent from the search index and published content

## ADDED Requirements

### Requirement: Documentation input selection follows canonical content

Documentation validation and publication SHALL account for every canonical file included in the site, including example instructions and source code. Development-only documentation changes SHALL NOT select a site build or publication solely because they are under `docs/`. Public-guide-only Markdown changes SHALL retain the existing behavior of not selecting Python package or database tests. Existing strict-build failures and least-privilege publication boundaries SHALL remain effective.

#### Scenario: An example included in the site changes

- **WHEN** a change modifies example instructions or executable source rendered on the site
- **THEN** documentation validation selects a build and the publication workflow recognizes the changed input on the default branch

#### Scenario: A maintainer note changes

- **WHEN** a change modifies only repository-only development Markdown
- **THEN** ordinary documentation formatting and link checks remain applicable, but the change does not select a site build or publication
