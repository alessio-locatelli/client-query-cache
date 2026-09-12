## ADDED Requirements

### Requirement: Pytest excludes Git-submodule contents

Every pytest invocation provided by the repository, including unit, integration, end-to-end,
coverage, and every tox test tier, SHALL exclude the working-tree contents below the registered
`specifications` Git submodule. The exclusion SHALL apply even when test discovery begins at the
repository root and SHALL not omit repository-owned tests.

#### Scenario: A provided test tier encounters a submodule test

- **WHEN** a contributor runs any documented pytest-based test tier with a Git submodule present
- **THEN** pytest does not collect or execute tests below that submodule and continues to collect the
  tier's repository-owned tests
