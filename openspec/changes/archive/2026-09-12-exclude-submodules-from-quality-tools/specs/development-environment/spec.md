## ADDED Requirements

### Requirement: Quality tools exclude Git-submodule contents

Every formatter, validator, and linter provided by the repository SHALL exclude the working-tree
contents below the registered `specifications` Git submodule. This applies to hook-driven and
standalone quality commands, including commands that can write formatting fixes. The exclusion SHALL
preserve coverage of every repository-owned applicable file.

#### Scenario: A complete quality run encounters a submodule file

- **WHEN** a contributor runs the documented complete quality workflow with a Git submodule present
- **THEN** no formatter, validator, or linter reads, reports, or modifies files below that submodule
