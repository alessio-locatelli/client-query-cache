# Spec Delta

## Purpose

Keep executable development, test, benchmark, and CI dependencies current through reviewable update proposals without rewriting historical evidence or weakening reproducibility.

## ADDED Requirements

### Requirement: Executable pins have exclusive update ownership

Every external dependency version that selects an executable tool, interpreter, package, or container in repository-owned development, CI, tests, or benchmarks SHALL have an automatic updater. Dependabot SHALL remain responsible for supported manifests; Renovate SHALL handle the unsupported occurrences without competing update proposals for the same occurrence.

#### Scenario: An updater extracts dependencies

- **WHEN** both configured bots inspect the repository
- **THEN** every executable pin is assigned to exactly one bot, including Python MongoDB images, CI tool inputs, interpreter selections, pinned development-container tools, and downloaded tools

### Requirement: Coupled inputs update consistently

An automatic update SHALL update every coupled executable occurrence and derived cache identifier in its ownership group together. Download updates SHALL retain integrity verification and update the version, URL, expected tool version, and checksum consistently.

#### Scenario: Prek is updated

- **WHEN** an automatic proposal updates the Prek version used by CI and the development container
- **THEN** the installation pins and CI cache identity agree within the same proposal

#### Scenario: A download checksum cannot be resolved

- **WHEN** an update cannot resolve the checksum for the selected download artifact
- **THEN** it produces a visible diagnostic and no acceptable update can remove verification or retain a mismatched checksum

### Requirement: Updates preserve release policies and review

Update proposals SHALL retain exact version and existing digest pins, preserve image variants and configured release tracks, and require maintainer review without automatic merging. The default cadence SHALL be monthly; timestamp-aware sources SHALL wait at least seven days after release. Fedora DNF packages SHALL be an explicit unpinned exception: builds SHALL select packages from Fedora 44 repositories while retaining the Node.js 24 package track. These package names SHALL be excluded from bot version extraction.

#### Scenario: A new MongoDB major version is available

- **WHEN** an image is configured on the MongoDB 8.0 noble track and a newer major is published
- **THEN** its automatic proposal stays on 8.0 noble, while an intentional track change requires a separate maintainer decision

#### Scenario: Fedora packages are installed during a rebuild

- **WHEN** the development image is rebuilt
- **THEN** DNF resolves compatible package versions from Fedora 44 repositories, retaining the Node.js 24 package track without requiring bot updates to RPM pins

### Requirement: Evidence and compatibility declarations are excluded

The new pin automation SHALL exclude recorded benchmark inputs/results, illustrative test data, schema versions, project release versions, local image labels, and published compatibility floors. Existing package-manifest automation SHALL retain its existing scope.

#### Scenario: A recorded benchmark names an older MongoDB image

- **WHEN** the executable MongoDB pin is updated
- **THEN** historical reports and their fixed reproduction inputs retain the versions actually used

### Requirement: Update coverage is observable before activation

The repository SHALL provide reproducible extraction and replacement checks covering its executable pin inventory, ownership boundaries, coupled updates, and exclusions. Missing dependencies and registry or checksum lookup failures SHALL be visible rather than treated as successful coverage.

#### Scenario: A custom manager stops matching a tool pin

- **WHEN** dependency extraction is checked against the executable pin inventory
- **THEN** the missing occurrence is reported and activation or acceptance is blocked until coverage is restored
