# Spec Delta

## MODIFIED Requirements

### Requirement: Updates preserve release policies and review

Update proposals SHALL retain exact versions, existing digests, image variants, and configured release tracks, use monthly cadence, and merge automatically after required CI passes. Timestamped releases SHALL age at least seven days; missing timestamps SHALL NOT block indefinitely. Fedora DNF tools SHALL remain unpinned, resolve from Fedora 44 with Node.js 24, and be excluded from bot extraction.

#### Scenario: A new MongoDB major version is available

- **WHEN** an image is configured on the MongoDB 8.0 noble track and a newer major is published
- **THEN** its automatic proposal stays on 8.0 noble, while an intentional track change requires a separate maintainer decision

#### Scenario: Fedora packages are installed during a rebuild

- **WHEN** the development image is rebuilt
- **THEN** DNF resolves compatible package versions from Fedora 44 repositories, retaining the Node.js 24 package track without requiring bot updates to RPM pins

#### Scenario: A release has no timestamp

- **WHEN** a datasource returns an otherwise eligible release without a release timestamp
- **THEN** the absence of a timestamp does not block an update proposal indefinitely

## ADDED Requirements

### Requirement: Bots create and accept eligible updates automatically

Dependabot and Renovate SHALL create eligible update PRs without a manual dashboard action and request GitHub native automerge. After required CI and automated approval succeed, eligible updates SHALL merge without maintainer action. This policy SHALL apply to all update types permitted by existing release and ownership constraints. Missing setup or permissions SHALL produce a visible blocker, not a claim of successful activation.

#### Scenario: An eligible bot update passes CI

- **WHEN** a same-repository Dependabot or Renovate update targeting main passes all required checks against the current base and receives automated approval
- **THEN** GitHub merges it automatically using the permitted merge method without manual creation, approval, or merge

#### Scenario: A permitted major update passes CI

- **WHEN** a major dependency update is allowed by its existing update policy and passes required CI
- **THEN** its update type does not impose an extra manual-approval requirement

### Requirement: Required validation gates automatic merging

Automatic merging SHALL wait for all required validation checks for the latest revision tested against the current base. Required checks SHALL include quality prerequisites and scope selection so dependency-skipped jobs cannot mask failed prerequisites. Failed, cancelled, or pending required validation SHALL block merging; intentionally inapplicable path-selected jobs SHALL retain their existing skip behavior.

#### Scenario: Lint fails and downstream validation is skipped

- **WHEN** Prek fails and dependent expensive jobs are skipped
- **THEN** the failed required Prek check blocks automatic merging

#### Scenario: The base advances before acceptance

- **WHEN** main advances after a bot PR passes CI
- **THEN** the PR is updated and required validation succeeds against the current base before merging

### Requirement: Privileged bot PR management uses trusted metadata

Privileged approval and merge management SHALL act only on verified same-repository Dependabot and Renovate PRs targeting main. It SHALL use trusted workflow code and PR metadata without executing PR code or consuming PR artifacts. Normal contributor PRs SHALL retain their existing approval requirement. Bot merging SHALL preserve existing applicable post-merge workflow triggers.

#### Scenario: A contributor imitates a bot branch name

- **WHEN** a human or fork PR uses a bot-style branch name or title
- **THEN** it receives neither automated approval nor an automerge request from bot PR management

#### Scenario: A bot update changes a documentation build input

- **WHEN** an automatically accepted update changes a path matched by documentation publication
- **THEN** its merge remains eligible to trigger the existing post-merge documentation workflow

### Requirement: Dependabot version proposals have bounded volume

Each configured Dependabot ecosystem SHALL allow at most two concurrent version-update PRs while retaining its existing monthly schedule and cooldown. Guidance SHALL distinguish per-ecosystem limits from a repository-wide cap and explain that security updates have separate limits.

#### Scenario: An ecosystem reaches its version-update budget

- **WHEN** two version-update PRs are open for a configured Dependabot ecosystem
- **THEN** further version-update proposals for that ecosystem wait for available capacity

### Requirement: Hosted updates discover repository configuration

The repository SHALL retain one recognized root Renovate configuration with the hosted required-file guard enabled. Contributor guidance SHALL explain how to distinguish missing configuration from schedule, release-age, lookup, and update-limit restrictions. Configuration presence alone SHALL NOT be presented as proof of successful hosted processing.

#### Scenario: The hosted run creates no update PR

- **WHEN** a maintainer investigates a hosted run that creates no update PR
- **THEN** the guidance identifies the repository and revision, discovered configuration, and logged eligibility or failure reason to inspect without disabling the required-file guard

### Requirement: Dependency update policy reuses official presets

Renovate policy SHALL reuse official presets for best practices and semantic commits. Repository configuration SHALL specify only necessary overrides and ownership-specific rules, without restating inherited defaults. Preset adoption SHALL preserve exclusive bot ownership, release tracks, coupled updates, automated acceptance, and exclusive lockfile ownership.

#### Scenario: Best-practice presets are enabled

- **WHEN** Renovate resolves the repository policy
- **THEN** dependency commits use semantic prefixes and enabled updates remain confined to the existing executable inventory, excluding Dependabot-owned manifests and action references

#### Scenario: Best practices include weekly lockfile maintenance

- **WHEN** the best-practices preset is resolved
- **THEN** the weekly lockfile-maintenance subpreset is excluded and Renovate retains the disabled default without a repeated lockFileMaintenance setting

### Requirement: Ordinary update proposals have bounded volume

Ordinary Renovate updates SHALL be limited to two concurrent PRs and one newly created PR per hour, with the concurrent branch limit inherited from the PR limit. Contributor guidance SHALL explain that these limits apply to Renovate, do not control hosted polling, and have documented vulnerability-alert exceptions.

#### Scenario: The ordinary update queue is full

- **WHEN** two ordinary Renovate PRs are open and another eligible update exists
- **THEN** Renovate defers an additional ordinary update branch and PR until capacity is available

#### Scenario: The hourly proposal budget is used

- **WHEN** Renovate has created one ordinary update PR in the current hourly period
- **THEN** another ordinary update PR waits for a later hourly period

### Requirement: Automatic branch commits have a separate budget

Renovate SHALL limit ordinary automatic branch creation and rebasing to two pushed commits per hour. Contributor guidance SHALL distinguish this CI-load budget from PR creation limits and disclose manual-rebase and vulnerability-alert exceptions rather than promising an absolute bound on runs.

#### Scenario: An automatic rebase consumes the commit budget

- **WHEN** two ordinary branch creation or automatic rebase commits have been pushed in an hourly period
- **THEN** further ordinary automatic commits wait for a later hourly period

### Requirement: The monthly proposal window accommodates throttling

Renovate SHALL allow ordinary update branch creation throughout the first seven days of each month in UTC while retaining monthly cadence and existing release-age policy. Guidance SHALL explain that this window permits hosted processing but does not trigger it, and that blocked PRs or unavailable hosted runs can carry a backlog into a later month.

#### Scenario: The hosted app runs during the monthly window

- **WHEN** the app runs on the fifth day of a month and an update satisfies release policy and available budgets
- **THEN** the schedule permits its proposal without a manual scheduling override

#### Scenario: The hosted app runs outside the monthly window

- **WHEN** the app runs on the eighth day of a month
- **THEN** the schedule prevents ordinary new update branches without treating the recognized configuration as missing
