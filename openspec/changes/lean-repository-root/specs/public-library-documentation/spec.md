## MODIFIED Requirements

### Requirement: Combined builds discover the published release

Combined documentation builds SHALL discover the latest published stable GitHub Release and fetch its exact tag by default. PR validation and publication SHALL use the same discovery and assembly command without a maintained release baseline. An explicit local tag in the current layout SHALL remain usable for reproduction without release discovery. Discovery or fetch failures SHALL abort visibly without selecting local tags or development content as substitutes.

#### Scenario: A new stable release becomes available

- **WHEN** the next combined build starts after a stable release is published
- **THEN** its stable edition uses that release without a repository configuration update

#### Scenario: A contributor reproduces a specific release

- **WHEN** a contributor supplies an exact locally available release tag whose documentation sources use the current repository layout
- **THEN** assembly uses that tag without contacting GitHub to discover or fetch a release

#### Scenario: A tag uses a different documentation layout

- **WHEN** a contributor supplies a release tag that keeps its example sources outside the current layout
- **THEN** assembly exits unsuccessfully before installing a new artifact

#### Scenario: Release discovery or retrieval fails

- **WHEN** GitHub discovery or the selected tag fetch fails
- **THEN** the build exits unsuccessfully before installing a new artifact

### Requirement: Context7 selects public documentation sources

Context7 configuration SHALL select the authored public guides and root README. Snippet-wrapper example pages, repository-only development guides, OpenSpec artifacts, submodule specifications, and root maintainer instructions SHALL be excluded from its configured documentation inputs. Complete integration programs SHALL remain available through the existing hosted documentation; this configuration need not include them in Context7.

#### Scenario: Context7 selects repository inputs

- **WHEN** the configuration's include and exclude settings are applied
- **THEN** `docs/user` and `README.md` are eligible while `docs/user/examples`, `docs/examples`, `docs/development`, `docs/specifications`, `openspec`, `AGENTS.md`, `CLAUDE.md`, and `CONTRIBUTING.md` are not
