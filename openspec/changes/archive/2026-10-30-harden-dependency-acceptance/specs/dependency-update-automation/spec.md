## MODIFIED Requirements

### Requirement: Privileged bot PR management uses trusted metadata

Privileged approval and merge management SHALL act only on verified same-repository Dependabot and Renovate PRs targeting main. It SHALL use trusted workflow code and PR metadata without executing PR code or consuming PR artifacts. Normal contributor PRs SHALL retain their existing approval requirement. Bot merging SHALL preserve existing applicable post-merge workflow triggers.

#### Scenario: A contributor imitates a bot branch name

- **WHEN** a human or fork PR uses a bot-style branch name or title
- **THEN** it receives neither automated approval nor an automerge request from bot PR management

#### Scenario: A bot update changes a documentation build input

- **WHEN** an automatically accepted update changes a path matched by documentation publication
- **THEN** its merge remains eligible to trigger the existing post-merge documentation workflow

#### Scenario: An older validation run finishes

- **WHEN** a bot PR advances to a new revision before an older validation run completes
- **THEN** management for the older revision submits neither approval nor an automerge request for the new head

#### Scenario: A contributor pushes to a bot PR

- **WHEN** a contributor pushes a new revision to a bot-authored PR and its validation succeeds
- **THEN** unattended bot management submits neither approval nor an automerge request for that revision

#### Scenario: Several eligible PRs share the validated head

- **WHEN** more than one open eligible bot PR matches the validated head
- **THEN** management fails visibly and submits neither approval nor an automerge request

### Requirement: Repository delivery is separate from live activation

The code PR SHALL prepare configs, trusted workflows, and a post-merge operator checklist without changing live settings, provisioning Apps, or writing credentials. Automated acceptance SHALL remain inactive until operator setup establishes required checks and App access. Delivery SHALL distinguish repository validation from verified activation and document rollback for both code and live state.

#### Scenario: The repository PR is reviewed before activation

- **WHEN** the coding agent completes the repository changes
- **THEN** the PR contains the activation checklist and live settings and credentials have not been changed by that work

#### Scenario: App configuration is absent

- **WHEN** bot PR management runs for an eligible bot PR without its App configuration
- **THEN** it fails visibly and submits neither approval nor an automerge request

#### Scenario: A bot PR predates activation

- **WHEN** an authorized operator re-runs the bot-initiated validation of an existing bot PR after setup
- **THEN** the workflow verifies the live bot author, repository, base, and head before enabling native automerge and approving, without needing a new bot event

## ADDED Requirements

### Requirement: Approval follows a successful merge request

Bot PR management SHALL request native automerge for the validated head before approving that head and SHALL NOT merge the PR directly. A rejected automerge request SHALL fail management before any approval is submitted.

#### Scenario: Repository auto-merge is disabled

- **WHEN** an eligible bot PR is managed while the repository does not permit auto-merge
- **THEN** management fails visibly and the PR receives no automated approval

#### Scenario: The PR is already mergeable

- **WHEN** an eligible bot PR already satisfies every merge requirement, such as a maintainer approval, when management requests automerge
- **THEN** management fails visibly without merging or approving the PR
