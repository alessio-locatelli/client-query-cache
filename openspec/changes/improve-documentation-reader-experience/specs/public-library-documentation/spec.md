# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
