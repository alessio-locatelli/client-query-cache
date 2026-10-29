## MODIFIED Requirements

### Requirement: Updates preserve release policies and review

Update proposals SHALL retain exact version selection, digest pinning, and image variants, use monthly cadence except for weekly Rust toolchain checks, and merge automatically after required CI passes. Major updates SHALL have the same automatic creation and acceptance policy as other updates. Timestamped releases SHALL age at least seven days; missing timestamps SHALL NOT block indefinitely. Fedora DNF tools SHALL remain unpinned and excluded from bot extraction.

#### Scenario: A new MongoDB major version is available

- **WHEN** a newer MongoDB major has an eligible image tag
- **THEN** Dependabot automatically proposes the newer major for the shared MongoDB image that the local service, tests, benchmarks, and research harnesses read, and the PR merges after required CI and automated approval without a separate maintainer decision

#### Scenario: A new stable Rust release is available

- **WHEN** a newer stable Rust release, including a patch release, has aged seven days
- **THEN** the next weekly Dependabot check proposes that exact release for the toolchain selection

#### Scenario: Fedora packages are installed during a rebuild

- **WHEN** the development image is rebuilt
- **THEN** DNF resolves package versions from the selected Fedora base repositories without requiring bot updates to RPM pins

#### Scenario: A release has no timestamp

- **WHEN** a datasource returns an otherwise eligible release without a release timestamp
- **THEN** the absence of a timestamp does not block an update proposal indefinitely

### Requirement: Dependabot version proposals have bounded volume

Each configured Dependabot ecosystem SHALL allow at most two concurrent version-update PRs while retaining its configured schedule and cooldown. Guidance SHALL distinguish per-ecosystem limits from a repository-wide cap and explain that security updates have separate limits.

#### Scenario: An ecosystem reaches its version-update budget

- **WHEN** two version-update PRs are open for a configured Dependabot ecosystem
- **THEN** further version-update proposals for that ecosystem wait for available capacity
