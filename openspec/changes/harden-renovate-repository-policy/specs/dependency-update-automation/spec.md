# Spec Delta

## MODIFIED Requirements

### Requirement: Updates preserve release policies and review

Update proposals SHALL retain exact version selection, digest pinning, and image variants, use monthly cadence, and merge automatically after required CI passes. Major updates SHALL have the same automatic creation and acceptance policy as other updates, without repository version caps. Timestamped releases SHALL age at least seven days; missing timestamps SHALL NOT block indefinitely. Fedora DNF tools SHALL remain unpinned and excluded from bot extraction.

#### Scenario: A new MongoDB major version is available

- **WHEN** a newer MongoDB major has an eligible noble image tag
- **THEN** Renovate automatically proposes the newer major for both test and benchmark images, and the PR merges after required CI and automated approval without a separate maintainer decision

#### Scenario: Fedora packages are installed during a rebuild

- **WHEN** the development image is rebuilt
- **THEN** DNF resolves package versions from the selected Fedora base repositories without requiring bot updates to RPM pins

#### Scenario: A release has no timestamp

- **WHEN** a datasource returns an otherwise eligible release without a release timestamp
- **THEN** the absence of a timestamp does not block an update proposal indefinitely

## ADDED Requirements

### Requirement: Bots create and accept eligible updates automatically

Dependabot and Renovate SHALL create eligible update PRs without manual dashboard action. Eligible PRs SHALL have GitHub native automerge requested automatically and merge after required CI and automated approval without maintainer action. Major, minor, patch, and digest updates SHALL share the same acceptance policy within existing bot ownership. Missing setup or permissions SHALL produce a visible blocker.

#### Scenario: An eligible bot update passes CI

- **WHEN** a same-repository Dependabot or Renovate update targeting main passes all applicable required checks for its latest revision and receives automated approval
- **THEN** GitHub merges it automatically using the permitted merge method without manual creation, approval, or merge

#### Scenario: A major update passes CI

- **WHEN** a bot proposes a major dependency update and it passes required CI
- **THEN** automated approval and native automerge accept it under the same policy as other updates

### Requirement: Required validation gates automatic merging

Automatic merging SHALL wait for all applicable required checks for the latest PR revision, without requiring the branch to be current with main. Required checks SHALL include quality prerequisites and scope selection so dependency-skipped jobs cannot mask failed prerequisites. Failed, cancelled, or pending required validation SHALL block merging; intentionally inapplicable path-selected jobs SHALL retain their existing skip behavior.

#### Scenario: Lint fails and downstream validation is skipped

- **WHEN** Prek fails and dependent expensive jobs are skipped
- **THEN** the failed required Prek check blocks automatic merging

#### Scenario: The base advances before acceptance

- **WHEN** main advances without conflicting with an approved bot PR whose latest revision passed required CI
- **THEN** being behind main alone does not block native automerge or require a maintainer to update the branch

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

Renovate policy SHALL reuse official presets for best practices and semantic commits. Repository configuration SHALL specify only necessary overrides and ownership-specific rules, without restating inherited defaults. Preset adoption SHALL preserve exclusive bot ownership, coupled updates, automated acceptance, and exclusive lockfile ownership without restricting major updates.

#### Scenario: Best-practice presets are enabled

- **WHEN** Renovate resolves the repository policy
- **THEN** dependency commits use semantic prefixes and enabled updates remain confined to the existing executable inventory, excluding Dependabot-owned manifests and action references

#### Scenario: Best practices include unwanted subpresets

- **WHEN** the best-practices preset is resolved
- **THEN** weekly lockfile maintenance and experimental configuration migration are excluded without restating their disabled defaults

#### Scenario: An inherited preset ignores test directories

- **WHEN** Renovate resolves the best-practices baseline for its MongoDB custom manager
- **THEN** the nested test-directory ignore preset is excluded, so both test and benchmark image occurrences remain available for coupled extraction

### Requirement: Ordinary update proposals have bounded volume

Ordinary Renovate updates SHALL be limited to two concurrent PRs and three newly created PRs per hour, with the concurrent branch limit inherited from the PR limit. Contributor guidance SHALL explain that these limits apply to Renovate, do not control hosted polling, and have documented vulnerability-alert exceptions.

#### Scenario: The ordinary update queue is full

- **WHEN** two ordinary Renovate PRs are open and another eligible update exists
- **THEN** Renovate defers an additional ordinary update branch and PR until capacity is available

#### Scenario: The hourly proposal budget is used

- **WHEN** Renovate has created three ordinary update PRs in the current hourly period
- **THEN** another ordinary update PR waits for a later hourly period

### Requirement: Automatic branch commits have a separate budget

Renovate SHALL limit ordinary automatic branch creation and rebasing to four pushed commits per hour. Contributor guidance SHALL distinguish this CI-load budget from PR creation limits and disclose manual-rebase and vulnerability-alert exceptions rather than promising an absolute bound on runs.

#### Scenario: An automatic rebase consumes the commit budget

- **WHEN** four ordinary branch creation or automatic rebase commits have been pushed in an hourly period
- **THEN** further ordinary automatic commits wait for a later hourly period

### Requirement: The monthly proposal window accommodates throttling

Renovate SHALL allow ordinary update branch creation throughout the first seven days of each month in UTC while retaining monthly cadence and existing release-age policy. Guidance SHALL explain that this window permits hosted processing but does not trigger it, and that blocked PRs or unavailable hosted runs can carry a backlog into a later month.

#### Scenario: The hosted app runs during the monthly window

- **WHEN** the app runs on the fifth day of a month and an update satisfies release policy and available budgets
- **THEN** the schedule permits its proposal without a manual scheduling override

#### Scenario: The hosted app runs outside the monthly window

- **WHEN** the app runs on the eighth day of a month
- **THEN** the schedule prevents ordinary new update branches without treating the recognized configuration as missing

### Requirement: Repository delivery is separate from live activation

The code PR SHALL prepare configs, trusted workflows, and a post-merge operator checklist without changing live settings, provisioning Apps, or writing credentials. Automated acceptance SHALL remain inactive until operator setup establishes required checks and App access. Delivery SHALL distinguish repository validation from verified activation and document rollback for both code and live state.

#### Scenario: The repository PR is reviewed before activation

- **WHEN** the coding agent completes the repository changes
- **THEN** the PR contains the activation checklist and live settings and credentials have not been changed by that work

#### Scenario: App configuration is absent

- **WHEN** bot PR management runs without its App configuration
- **THEN** it visibly reports inactive acceptance and submits neither approval nor an automerge request

#### Scenario: A bot PR predates activation

- **WHEN** an authorized operator dispatches management on main for an existing bot PR after setup
- **THEN** the workflow verifies the live bot author, repository, base, and head before approving and enabling native automerge without needing a new bot event
