# Spec Delta

## ADDED Requirements

### Requirement: Agent discovery groups public documentation

The documentation SHALL expose `llms.txt` with named, populated sections for Home / overview, Getting started, Usage, Examples, API reference, Operations, and Benchmarks. Its links SHALL use the deployed canonical documentation URL and resolve to generated Markdown. Selection SHALL include new public pages within existing sections automatically and exclude repository-only development material.

#### Scenario: An agent discovers public guidance

- **WHEN** an agent reads the documentation's `llms.txt`
- **THEN** it receives useful section headings and links to Markdown guidance under the deployed documentation URL

#### Scenario: A contributor adds a public page

- **WHEN** a contributor adds a page, including a nested page, within an existing selected public section and builds that corpus
- **THEN** the page appears in that section of `llms.txt` and has a generated Markdown equivalent without a separate export entry

#### Scenario: A build selects public content

- **WHEN** an agent reads generated indexes or exported documentation
- **THEN** repository-only development documents, OpenSpec artifacts, and raw library source trees are absent as exported pages

### Requirement: Markdown equivalents contain rendered documentation

Every page selected for agent discovery SHALL have a clean Markdown equivalent containing its rendered documentation content, including expanded snippets, code examples, and relevant links. Exports SHALL omit site navigation and theme controls while preserving meaningful headings, prose, code, tables, and links.

#### Scenario: A tool retrieves an example as Markdown

- **WHEN** a tool retrieves the selected example catalogue or an integration page's Markdown equivalent
- **THEN** it receives the expanded catalogue or complete included program rather than an unresolved snippet directive

#### Scenario: A tool retrieves reference or operations guidance

- **WHEN** a tool retrieves a selected reference, operations, or benchmark page as Markdown
- **THEN** its guidance, code, tables, and links remain readable without HTML navigation or theme controls

### Requirement: Combined documentation is available as text

The documentation SHALL expose `llms-full.txt` containing the selected rendered public documentation in section order when its measured size remains practical for this project. Generation SHALL be enabled by default; disabling it SHALL require recorded build measurements and a concrete size or usability reason. A combined document SHALL contain one edition's guidance without mixing stable and development content.

#### Scenario: A tool consumes the current combined corpus

- **WHEN** a documentation build produces a reasonably sized combined corpus
- **THEN** `llms-full.txt` exists and contains the selected pages' rendered content, including expanded examples

#### Scenario: Combined output becomes impractical

- **WHEN** measured combined output demonstrates a concrete size or usability problem
- **THEN** any decision to omit it records that evidence while retaining the sectioned index and per-page Markdown

### Requirement: HTML pages offer Copy as Markdown

Selected documentation pages SHALL expose a Copy as Markdown action that copies their generated Markdown equivalent. HTML content, navigation, search, appearance, and edition selection SHALL preserve their existing behavior apart from this added action.

#### Scenario: A reader copies rendered guidance

- **WHEN** a reader invokes Copy as Markdown on a selected example or guide page
- **THEN** the copied content is its generated Markdown, including any expanded snippets, and ordinary HTML reading remains usable

### Requirement: Agent exports respect documentation editions

Published stable and development editions SHALL each expose indexes, selected Markdown pages, and any enabled combined output for their own source corpus. Documentation-root `llms.txt` and any enabled `llms-full.txt` SHALL expose stable guidance. Generated index and document links SHALL remain within the corresponding edition except for intentional external references.

#### Scenario: An agent starts at the documentation root

- **WHEN** an agent retrieves root `llms.txt` or `llms-full.txt` from the assembled publication artifact
- **THEN** it receives stable guidance and Markdown links resolve within the stable edition

#### Scenario: An agent chooses development guidance

- **WHEN** an agent retrieves the development edition's index or combined document
- **THEN** it receives that edition's public content and links resolve within the development edition

#### Scenario: Stable sources predate agent exports

- **WHEN** publication uses an accepted immutable stable documentation source created before export support and a development corpus containing an additional page
- **THEN** stable exports are still generated from that stable corpus, without importing the development-only page or changing its source provenance

### Requirement: Agent exports follow ordinary documentation builds

Ordinary local and publication documentation builds SHALL regenerate agent-facing files from the same canonical inputs as HTML, without a separate generation command or manual synchronization. Generated exports SHALL remain untracked in the source checkout. Existing strict validation and documentation CI SHALL remain effective.

#### Scenario: Canonical content changes

- **WHEN** a contributor changes a selected guide or included example and rebuilds that corpus using normal documentation tooling
- **THEN** HTML, per-page Markdown, indexes, and enabled combined output reflect that revision without editing generated files

#### Scenario: A clean build removes a public page

- **WHEN** a selected page is removed and the corpus is rebuilt using the normal clean build
- **THEN** its Markdown output and discovery entry disappear rather than remaining as stale documentation

#### Scenario: Publication assembles the output

- **WHEN** the existing documentation publication build succeeds
- **THEN** its complete artifact includes the native exports alongside HTML without requiring tracked generated files in the source checkout
