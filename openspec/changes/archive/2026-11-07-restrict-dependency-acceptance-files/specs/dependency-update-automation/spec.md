## ADDED Requirements

### Requirement: Automated acceptance is limited to dependency-update files

Bot PR management SHALL issue acceptance credentials and request approval or automerge only when every changed path belongs to an explicit allowlist covering the configured dependency-update inventory. Renames SHALL satisfy the policy for both paths. Out-of-scope PRs SHALL receive a visible notice and require human review. Major, minor, patch, and digest eligibility SHALL remain unchanged. This boundary SHALL NOT claim to verify the contents of allowed files.

#### Scenario: A dependency update also edits library source

- **WHEN** an otherwise eligible bot PR changes a dependency manifest and Python or Rust source
- **THEN** management issues no acceptance token and submits neither approval nor an automerge request

#### Scenario: An executable pin is outside package manifests

- **WHEN** an otherwise eligible bot PR changes only allowlisted workflow, container, command-runner, or interpreter pin files
- **THEN** file scope does not prevent automated acceptance

#### Scenario: Source is renamed into an allowed file

- **WHEN** a bot PR renames an out-of-scope file into an allowlisted path
- **THEN** management refuses automated acceptance

### Requirement: Acceptance verifies a complete and stable file scope

Management SHALL fail visibly on API errors, malformed file responses, or incomplete file enumeration before issuing credentials or submitting acceptance requests. It SHALL require a nonempty file list matching the PR's reported changed-file count. Changes to the verified head or base during management SHALL prevent further acceptance requests.

#### Scenario: A later page contains an unrelated file

- **WHEN** an unrelated changed path occurs after the first page of the file listing
- **THEN** management refuses automated acceptance

#### Scenario: GitHub cannot provide the complete file list

- **WHEN** the returned file count differs from PR metadata, including an API truncation
- **THEN** management fails without issuing credentials or submitting acceptance requests

#### Scenario: The diff changes during management

- **WHEN** the PR head or base changes after the file-scope snapshot
- **THEN** management submits no further approval or automerge request using that snapshot
