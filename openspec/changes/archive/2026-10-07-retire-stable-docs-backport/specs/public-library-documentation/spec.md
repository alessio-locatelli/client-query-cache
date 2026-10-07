## MODIFIED Requirements

### Requirement: Stable documentation matches the published package

The stable edition SHALL describe the latest published non-prerelease package and identify its version. Development-only API changes SHALL NOT appear as stable guidance. Stable guides and examples SHALL come directly from that release’s exact tag, without correction revisions. Drafts, prereleases, and failed package publication SHALL NOT advance the stable edition.

#### Scenario: Development gains an unreleased option

- **WHEN** an API change exists on `main` but not in the latest published stable package
- **THEN** it appears only in development documentation

#### Scenario: A release is published successfully

- **WHEN** a newer stable package and its corresponding GitHub Release are published
- **THEN** the default edition documents that release and identifies its version

#### Scenario: A release is not ready for stable users

- **WHEN** a release is a draft, prerelease, or failed package publication
- **THEN** it does not replace the stable edition

### Requirement: Agent exports respect documentation editions

Published stable and development editions SHALL each expose indexes, selected Markdown pages, and any enabled combined output for their own source corpus. Documentation-root `llms.txt` and any enabled `llms-full.txt` SHALL expose stable guidance. Generated index and document links SHALL remain within the corresponding edition except for intentional external references.

#### Scenario: An agent starts at the documentation root

- **WHEN** an agent retrieves root `llms.txt` or `llms-full.txt` from the assembled publication artifact
- **THEN** it receives stable guidance and Markdown links resolve within the stable edition

#### Scenario: An agent chooses development guidance

- **WHEN** an agent retrieves the development edition's index or combined document
- **THEN** it receives that edition's public content and links resolve within the development edition

#### Scenario: Stable sources predate agent exports

- **WHEN** a selected stable release lacks native export configuration
- **THEN** assembly fails visibly without borrowing development settings or replacing a previously complete artifact

### Requirement: Edition export policies follow source snapshots

Each documentation edition SHALL preserve its source snapshot’s export policy, including page selection, section names and order, description, and combined-output setting. A source lacking required export settings SHALL fail visibly rather than inherit another edition’s policy. Root discovery and combined exports SHALL follow the stable policy.

#### Scenario: Development changes a released export policy

- **WHEN** stable sources define an export policy and development changes section paths, description, order, or combined output
- **THEN** stable and root exports preserve the stable policy while development exports follow development’s policy

#### Scenario: A selected source lacks required exports

- **WHEN** a selected documentation snapshot has no native export configuration
- **THEN** assembly fails visibly without replacing a previously complete artifact

### Requirement: Hosted learning journeys are self-contained

Readers SHALL proceed from installation through synchronous or asyncio usage, workload evaluation, integrations, and API details on rendered site pages. Hosted tutorials and examples SHALL NOT substitute GitHub READMEs for guidance. Examples SHALL show prerequisites, commands, integration explanations, and relevant code. External source, checkout, upstream-documentation, and benchmark-evidence links SHALL be explicitly identified.

#### Scenario: A reader learns the library on the site

- **WHEN** a reader follows getting-started and usage navigation from the landing page
- **THEN** installation and complete synchronous and asyncio quick starts render on the site, with manager cleanup, raw writes, cursor-returning reads, and eventual invalidation explained

#### Scenario: A reader studies an integration

- **WHEN** a reader opens the site's examples section
- **THEN** delivered examples have hosted prerequisites, run commands, explanations, and relevant integration code, while optional links to source files are clearly identified

## ADDED Requirements

### Requirement: Combined builds discover the published release

Combined documentation builds SHALL discover the latest published stable GitHub Release and fetch its exact tag by default. PR validation and publication SHALL use the same discovery and assembly command without a maintained release baseline. An explicit locally available tag SHALL remain usable for reproduction without release discovery. Discovery or fetch failures SHALL abort visibly without selecting local tags or development content as substitutes.

#### Scenario: A new stable release becomes available

- **WHEN** the next combined build starts after a stable release is published
- **THEN** its stable edition uses that release without a repository configuration update

#### Scenario: A contributor reproduces a specific release

- **WHEN** a contributor supplies an exact locally available release tag
- **THEN** assembly uses that tag without contacting GitHub to discover or fetch a release

#### Scenario: Release discovery or retrieval fails

- **WHEN** GitHub discovery or the selected tag fetch fails
- **THEN** the build exits unsuccessfully before installing a new artifact

## REMOVED Requirements

### Requirement: Stable correction provenance survives merge changes

**Reason**: Supported stable sources contain the complete documentation layout and exports, so a separate correction revision has no active use.

**Migration**: Build stable documentation directly from the discovered release tag.
