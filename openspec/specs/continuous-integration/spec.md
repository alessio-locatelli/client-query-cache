# continuous-integration Specification

## Purpose

This capability gives external contributors hosted, repeatable evidence that the locked project and its database-backed test tiers work together.

## Requirements

### Requirement: Every pull request runs basic quality gates

GitHub Actions SHALL run Prek and Justfile formatting validation for every pull request, and formatting checks when supported files change.

#### Scenario: A documentation file changes

- **WHEN** a pull request changes only Markdown files
- **THEN** the Prek and formatting jobs run, and the Python package and test jobs do not run

### Requirement: CI rejects unlocked dependencies

When the Python gate runs, CI SHALL synchronize committed `uv.lock` without modification.

#### Scenario: Dependency metadata is unlocked

- **WHEN** a change modifies dependency metadata without the corresponding lockfile update
- **THEN** the Python package job fails before accepting the change

### Requirement: Python changes run build and test gates

Python, pytest, project-metadata, or lockfile changes SHALL run static checks, build source and wheel distributions, install the wheel in isolation, and test CPython 3.14.

#### Scenario: A Python file changes

- **WHEN** a pull request changes a Python file
- **THEN** the Python package job runs the static checks and package-artifact validation

### Requirement: CI runs database-backed tests in an owned runtime

GitHub Actions SHALL run integration and end-to-end tests using Docker and the disposable replica-set
fixture when a pull request changes Python files, `pytest.ini`, `pyproject.toml`, or `uv.lock`. It SHALL
retain safe diagnostic artifacts on failure and SHALL not depend on a shared external database.

#### Scenario: A cache change is proposed

- **WHEN** a pull request changes a Python file
- **THEN** the Docker-backed job executes the integration and end-to-end test tiers before reporting
  success

#### Scenario: A documentation-only change is proposed

- **WHEN** a pull request changes only files outside the Python-validation path set
- **THEN** the Docker-backed job is not started

### Requirement: Expensive pull request validation waits for quality checks

GitHub Actions SHALL complete applicable linting and formatting checks successfully before starting package validation, database-backed tests, or the pull request performance comparison. Those expensive checks SHALL be skipped when a required quality check fails. Independent checks within each stage SHALL remain able to run concurrently.

#### Scenario: Linting fails on a Python change

- **WHEN** a pull request changes Python code and its linting check fails
- **THEN** package validation, database-backed tests, and the performance comparison do not start

#### Scenario: Formatting fails on a Python change

- **WHEN** a pull request changes Python code and a supported formatting input, and formatting fails
- **THEN** package validation, database-backed tests, and the performance comparison do not start

#### Scenario: Quality checks pass

- **WHEN** applicable quality checks pass on a Python change
- **THEN** package validation, database-backed tests, and the performance comparison can start concurrently

### Requirement: CI preserves reusable validation caches

GitHub Actions SHALL restore and save reusable caches produced by validation tools across compatible runs. Cache keys SHALL prevent reuse across incompatible toolchains or dependency sets, while allowing later commits to reuse prior compatible cache entries. Validation results SHALL remain authoritative when a cache is absent or stale.

#### Scenario: A later pull request run checks unchanged inputs

- **WHEN** a validation job runs with a compatible toolchain and dependency set after an earlier run saved a cache
- **THEN** the job restores that cache and saves updated reusable state for a subsequent run

#### Scenario: A validation cache is unavailable

- **WHEN** a compatible cache cannot be restored
- **THEN** the validation job still runs the full required checks and reports their actual results

### Requirement: Executable pin changes validate affected consumers

Pull requests changing executable dependency configuration SHALL run validation of the affected consumers even when no Python source changes. MongoDB Testcontainers image updates SHALL run owned-runtime integration and end-to-end tests and a bounded isolated benchmark startup check. Development-container pin or download-integrity updates SHALL build the image and verify its declared tools. Python or shared Python-toolchain updates SHALL run package validation and database-backed tests. Expensive consumer checks SHALL wait for applicable quality checks.

#### Scenario: A MongoDB pin changes without Python source edits

- **WHEN** a pull request updates a configuration value consumed by the test and benchmark replica sets
- **THEN** CI runs database-backed tests and checks isolated benchmark startup under the selected image

#### Scenario: A development-container package changes

- **WHEN** a pull request updates a Containerfile package, base image, or Taplo download
- **THEN** CI builds that definition and verifies the pinned tools after applicable quality checks pass

#### Scenario: An interpreter selection changes

- **WHEN** a pull request updates an executable Python selection without changing Python source
- **THEN** package validation and database-backed tests run using the proposed interpreter and performance comparisons retain their matched-interpreter constraint

#### Scenario: An unrelated document changes

- **WHEN** a pull request changes only documentation unrelated to executable inputs
- **THEN** these additional consumer checks do not run

### Requirement: Pull requests validate documentation-site inputs

Pull requests that change rendered documentation sources or assets, site configuration, documentation dependencies, build recipes, the publishing workflow, or shared toolchain setup SHALL run a clean strict documentation build after applicable linting and formatting gates succeed. Other pull requests SHALL retain a stable documentation-check outcome without executing an unnecessary site build. Documentation build failures SHALL prevent successful validation. Documentation-only Markdown changes SHALL not add Python package or database test execution beyond the existing validation scope.

#### Scenario: A guide changes

- **WHEN** a pull request changes a public guide and its applicable quality gates pass
- **THEN** CI builds the documentation and reports its actual success or failure without starting Python package or database tests for that Markdown-only change

#### Scenario: A shared input changes

- **WHEN** a pull request changes the lockfile, site configuration, or shared toolchain setup
- **THEN** CI selects the documentation build even when no guide changed

#### Scenario: Quality checks fail

- **WHEN** a pull request fails an applicable linting or formatting gate
- **THEN** the documentation build does not start and the failed prerequisite remains independently visible as a merge-blocking check when merge rules are configured

### Requirement: Documentation deployment promotes trusted built artifacts

Relevant changes on `main` SHALL build and publish the documentation automatically after repository hosting is configured. A manual redeploy SHALL also be available for `main`. Deployment SHALL publish the artifact produced by the successful build for the same revision. Pull requests and other branches SHALL not deploy or receive documentation publishing permissions. Build, hosting configuration, or deployment failures SHALL be reported visibly and SHALL not publish a failed build artifact.

#### Scenario: Documentation is merged

- **WHEN** a relevant change reaches `main` and its documentation build succeeds
- **THEN** a separate deployment stage publishes that revision's artifact and reports the deployed URL

#### Scenario: A fork proposes a documentation change

- **WHEN** a fork pull request runs documentation validation
- **THEN** it can build the site with read-only repository access and cannot deploy to the public site

#### Scenario: A manual redeploy targets another branch

- **WHEN** a manual documentation workflow run selects a branch other than `main`
- **THEN** it does not receive publishing permissions or deploy the site

#### Scenario: A build or deployment fails

- **WHEN** a documentation build fails or the hosting service rejects deployment
- **THEN** the workflow reports failure and a failed build is not promoted to the public site

### Requirement: Newer documentation publication runs supersede older ones

At most one documentation publication run SHALL hold the site at a time. A newer eligible run SHALL cancel the run holding the site, whether that run is queued, building, or deploying, so a run that never starts or never finishes cannot block later publication. A run that is ineligible to publish SHALL neither cancel nor replace an eligible run.

#### Scenario: A deploy job is never assigned a runner

- **WHEN** an eligible run's deploy job stays queued and a later eligible run starts
- **THEN** the later run cancels the stuck run and publishes the site

#### Scenario: Changes reach `main` during a deployment

- **WHEN** an eligible run starts while an earlier eligible run is building or deploying
- **THEN** the earlier run is cancelled, the site keeps its previously published content until the newer run deploys, and the newer run publishes current `main`

#### Scenario: Package publication fails during a deployment

- **WHEN** a documentation run triggered by an unsuccessful package publication starts while an eligible run is in progress or pending
- **THEN** the eligible run continues and the ineligible run skips its jobs

#### Scenario: A manual run targets another branch during a deployment

- **WHEN** a manual documentation run from a branch other than `main` starts while an eligible run is in progress or pending
- **THEN** the eligible run continues and the manual run deploys nothing

### Requirement: Pull requests run an isolated memory gate

Pull requests selected by the existing Python-validation path scope SHALL run the memory command in a dedicated Linux job using the locked dependencies and repository interpreter. The job SHALL wait for applicable quality checks, require no MongoDB, and fail on memory assertions or profiling errors. Unrelated documentation-only changes SHALL not start it. Cached results SHALL not determine thresholds.

#### Scenario: Python validation is selected

- **WHEN** Python source, pytest or coverage configuration, dependency metadata, lockfile, interpreter, test recipe, validation workflow, or shared toolchain setup changes and quality checks pass
- **THEN** a separate memory job runs the dedicated command on the selected revision

#### Scenario: Quality checks fail

- **WHEN** a required linting or formatting check fails
- **THEN** the memory workload does not start

#### Scenario: An unrelated document changes

- **WHEN** a pull request changes only documentation outside the Python-validation scope
- **THEN** no memory workload runs

### Requirement: Memory failures preserve safe diagnostics

The memory job SHALL retain allocation traces and useful failure output for seven days on failure. Diagnostics SHALL contain only synthetic workload data and SHALL remain untracked. Documentation SHALL identify the reproduction command, workload, measured scope, calibrated ceilings, and runtime overhead.

#### Scenario: A ceiling is exceeded

- **WHEN** the memory command fails after producing an allocation trace
- **THEN** CI exposes the failure output and uploads the trace with seven-day retention

#### Scenario: Profiling fails before producing a trace

- **WHEN** dependency loading or profiling fails before a trace exists
- **THEN** the job remains failed and the original error remains visible

### Requirement: Parallel test failures retain worker diagnostics

The existing database-backed CI job SHALL retain controller and worker log files in its failure artifact for seven days. Missing log files SHALL not replace or hide the original test failure.

#### Scenario: A parallel test fails

- **WHEN** the database-backed coverage command fails after workers produce logs
- **THEN** the existing diagnostic artifact contains controller and worker files with seven-day retention

#### Scenario: Failure precedes worker logging

- **WHEN** the command fails before worker log files exist
- **THEN** CI reports the original command failure without requiring absent log files

### Requirement: Lychee installation uses scoped read-only authentication

The pull request quality gate SHALL authenticate Lychee's GitHub release installation using the read-only job token, scoped to the Lychee hook invocation. Other hook invocations SHALL not receive that token through the environment. Link validation SHALL remain required regardless of installation or result-cache availability, and installation or link-check failures SHALL fail the gate.

#### Scenario: The hook installation cache is absent

- **WHEN** a pull request runner needs to install the pinned Lychee release
- **THEN** the release installer receives the read-only job token and the hook checks the selected files after installation

#### Scenario: A fork pull request needs installation

- **WHEN** a fork pull request runs the quality gate without a cached Lychee binary
- **THEN** the installer uses the automatic read-only job token without requiring a custom repository secret

#### Scenario: Validation fails

- **WHEN** Lychee installation or link validation fails
- **THEN** the Prek quality gate fails and its dependent expensive jobs do not start

#### Scenario: Other hooks run

- **WHEN** the quality gate invokes the other Prek hooks
- **THEN** their environment does not contain the token supplied to the Lychee installer
