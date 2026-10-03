# public-library-documentation Specification

## Purpose

This capability gives public users accurate, evidence-backed documentation for the implemented MongoDB client-side cache and its operating boundaries.

## Requirements

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

### Requirement: Public documentation is available as a free hosted site

The library SHALL provide a public HTTPS documentation site usable without an account, paid hosting plan, or custom domain. README and package metadata SHALL identify its URL. The site SHALL offer latest stable release and development editions, default to stable, and clearly identify the release version or `main` state being documented.

#### Scenario: A reader discovers the documentation

- **WHEN** a reader follows the documentation link from the README or package metadata
- **THEN** the reader can open the public site without authentication and identify the release version or development state it documents

### Requirement: Documentation navigation supports common reader tasks

The site SHALL provide a landing page and populated sections for getting started, usage, benchmarks, examples, reference, and operations. It SHALL support full-text search, mobile navigation, keyboard access to navigation and search, light/dark appearance selection, readable code blocks, heading permalinks, and Previous/Next footer links in the configured reading order.

#### Scenario: A reader locates an API option

- **WHEN** a reader searches for `max_await_time_ms`
- **THEN** the search returns relevant API guidance and allows the reader to open that section

#### Scenario: A reader uses a small screen or keyboard

- **WHEN** a reader navigates on a mobile viewport or uses only a keyboard
- **THEN** the reader can open navigation, reach the API guide, use search, and read code without page-wide horizontal overflow

#### Scenario: A reader selects an appearance

- **WHEN** a reader switches between light and dark appearances
- **THEN** text, links, and code remain legible in the selected appearance

#### Scenario: A reader finishes a guide

- **WHEN** a reader reaches the end of an installation or tutorial page
- **THEN** the footer provides the next page in the reading order without generic onward-navigation paragraphs duplicating it

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

### Requirement: Documentation separates public and development sources

Public and development documentation SHALL occupy distinct, descriptively named subdirectories of `docs/`.

#### Scenario: A contributor locates documentation sources

- **WHEN** a contributor opens `docs/`
- **THEN** descriptive subdirectories distinguish published user guidance from repository-only development documentation

### Requirement: Documentation input selection follows canonical content

Documentation validation and publication SHALL select canonical site inputs, including example prose, code, and versioning inputs. Successful stable package publication SHALL refresh stable guidance; `main` inputs SHALL refresh development guidance. Development-only documentation SHALL NOT select site builds or publication. Public-guide-only Markdown SHALL NOT select Python package or database tests. Strict-build failures and least-privilege publication boundaries SHALL remain effective.

#### Scenario: An example included in the site changes

- **WHEN** a change modifies example instructions or executable source rendered on the site
- **THEN** documentation validation selects a build and the publication workflow recognizes the changed input on the default branch

#### Scenario: A maintainer note changes

- **WHEN** a change modifies only repository-only development Markdown
- **THEN** ordinary documentation formatting and link checks remain applicable, but the change does not select a site build or publication

### Requirement: README provides a concise entry point

The README SHALL provide a concise product introduction, an accurate Python-version badge, essential caching prerequisites linked to their explanation, installation, an asynchronous-invalidation caveat, and direct hosted getting-started and detailed-guide links. Detailed tutorials, configuration, and benchmark analysis SHALL have canonical guide destinations rather than parallel README sections.

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

### Requirement: Stable documentation matches the published package

The stable edition SHALL describe the latest published non-prerelease package and identify its version. Development-only API changes SHALL NOT appear as stable guidance. Reviewed documentation-only corrections MAY use a recorded immutable source revision matching that release’s runtime and package metadata. Drafts, prereleases, and failed package publication SHALL NOT advance the stable edition.

#### Scenario: Development gains an unreleased option

- **WHEN** an API change exists on `main` but not in the latest published stable package
- **THEN** it appears only in development documentation

#### Scenario: A release is published successfully

- **WHEN** a newer stable package and its corresponding GitHub Release are published
- **THEN** the default edition documents that release and identifies its version

#### Scenario: A release is not ready for stable users

- **WHEN** a release is a draft, prerelease, or failed package publication
- **THEN** it does not replace the stable edition

### Requirement: Edition selection preserves usable navigation

Readers SHALL be able to switch between exactly two visible editions from the documentation UI. Site links and search results SHALL remain within the selected edition. Switching SHALL retain the page when present in both editions, otherwise open the destination edition’s landing page. Existing unversioned public page and heading links SHALL continue to reach relevant stable guidance.

#### Scenario: A reader changes edition

- **WHEN** a reader selects development from the stable API page or switches back
- **THEN** the corresponding destination API page opens without mixing search results from the other edition

#### Scenario: A page is absent in the selected edition

- **WHEN** a reader switches editions from a page absent in the destination
- **THEN** the destination edition opens at its landing page

#### Scenario: A reader uses an existing direct link

- **WHEN** a reader opens an unversioned public page or documented heading URL
- **THEN** it reaches the relevant stable page and heading after edition publication

### Requirement: Installation guidance stays focused

The installation page SHALL cover requirements, installation, and the project’s local setup without repeating the landing-page introduction. Tutorials SHALL start with their example context rather than instructions to install the library. Generic “Continue with” paragraphs and a “First cached read” link list SHALL NOT substitute for footer navigation. Contextual links explaining code, limits, or errors SHALL remain available.

#### Scenario: A reader follows the installation journey

- **WHEN** a reader opens installation and continues to a tutorial
- **THEN** each page introduces its own task without repeating the product description, installation reminder, or next-page catalogue

### Requirement: Caching prerequisites are explicit

Public guidance SHALL state that caching requires MongoDB 8.0+ on a replica set or sharded cluster, with database change-stream access. It SHALL explain that standalone servers and older MongoDB versions perform uncached reads through PyMongo. It SHALL NOT describe this as varying caching “effectiveness” or merely restate PyMongo deployment support. The Python badge SHALL preserve the package’s declared minimum version.

#### Scenario: A reader checks a local standalone server

- **WHEN** a reader consults the README or installation requirements for a standalone MongoDB server
- **THEN** they learn that its reads bypass the cache, can follow the requirements explanation, and can identify how to enable caching locally

### Requirement: Local evaluation has a documented replica-set setup

The hosted installation guide SHALL identify the repository’s Compose file as an example local single-member replica-set setup, provide the project commands and connection string needed by its tutorials, and explain readiness and shutdown. Third-party tool installation SHALL link to official documentation. Local setup SHALL NOT be described as production deployment guidance.

#### Scenario: A reader tries caching locally

- **WHEN** a reader follows the project’s local setup from a checkout
- **THEN** they can start the configured replica set, establish that initialization succeeded, run a tutorial against it, and stop the services
