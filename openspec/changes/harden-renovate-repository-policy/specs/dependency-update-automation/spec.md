# Spec Delta

## ADDED Requirements

### Requirement: Hosted updates discover repository configuration

The repository SHALL retain one recognized root Renovate configuration with the hosted required-file guard enabled. Contributor guidance SHALL explain how to distinguish missing configuration from schedule, release-age, lookup, and update-limit restrictions. Configuration presence alone SHALL NOT be presented as proof of successful hosted processing.

#### Scenario: The hosted run creates no update PR

- **WHEN** a maintainer investigates a hosted run that creates no update PR
- **THEN** the guidance identifies the repository and revision, discovered configuration, and logged eligibility or failure reason to inspect without disabling the required-file guard

### Requirement: Dependency update policy reuses official presets

Renovate policy SHALL reuse official presets for best practices and semantic commits. Repository configuration SHALL specify only necessary overrides and ownership-specific rules, without restating inherited defaults. Preset adoption SHALL preserve exclusive bot ownership, release tracks, coupled updates, maintainer review, and disabled lockfile maintenance.

#### Scenario: Best-practice presets are enabled

- **WHEN** Renovate resolves the repository policy
- **THEN** dependency commits use semantic prefixes and enabled updates remain confined to the existing executable inventory, excluding Dependabot-owned manifests and action references

#### Scenario: A preset enables lockfile maintenance

- **WHEN** an inherited preset enables lockfile maintenance
- **THEN** the repository override disables it so Renovate does not compete with Dependabot

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

Renovate SHALL allow ordinary update branch creation throughout the first seven days of each month in UTC while retaining monthly cadence and existing release-age policy. Guidance SHALL explain that this window permits hosted processing but does not trigger it, and that open PRs or unavailable hosted runs can carry a backlog into a later month.

#### Scenario: The hosted app runs during the monthly window

- **WHEN** the app runs on the fifth day of a month and an update satisfies release policy and available budgets
- **THEN** the schedule permits its proposal without a manual scheduling override

#### Scenario: The hosted app runs outside the monthly window

- **WHEN** the app runs on the eighth day of a month
- **THEN** the schedule prevents ordinary new update branches without treating the recognized configuration as missing
