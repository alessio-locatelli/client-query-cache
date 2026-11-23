# Development environment delta

## ADDED Requirements

### Requirement: Root tool configuration uses supported locations

Contributor tool configuration SHALL live in `pyproject.toml` when a supported configuration format preserves project behavior. Other settings SHALL use a tool-supported location under an existing directory when established entry points can select it directly. Root discovery SHALL remain available where moving the file would require extra setup, a wrapper, or altered tool coverage.

#### Scenario: A contributor runs project checks in a fresh checkout

- **WHEN** a contributor runs the supported setup, quality, or test commands in a fresh checkout
- **THEN** the commands find the repository settings through normal discovery or their configured arguments and apply the existing validation rules

#### Scenario: Git invokes the installed commit hook

- **WHEN** a contributor submits a commit message after installing the project's hooks
- **THEN** the hook checks that message using the repository's commit rules

### Requirement: Generated development output uses an ignored location

Supported workflows SHALL place configurable diagnostic logs, generated reports, and generated site output below the ignored project cache by default. Conventional tool-owned locations remain valid for environments and tool caches. Explicit output paths SHALL continue to work wherever a workflow accepts them.

#### Scenario: Tests write controller and worker diagnostics

- **WHEN** a contributor runs the standard test command with parallel workers and no output override
- **THEN** the controller and each worker write distinct log files in the ignored output directory without creating log files at the repository root

#### Scenario: A contributor overrides test logging

- **WHEN** a contributor supplies a custom pytest log destination or disables file output with the null device
- **THEN** logs follow the chosen destination with separate worker files where applicable, or file output is disabled

#### Scenario: Existing local files occupy an output location

- **WHEN** the layout changes in a checkout with existing local reports, diagnostics, or recovery files
- **THEN** relocating local files preserves their contents and leaves conflicting destinations untouched
