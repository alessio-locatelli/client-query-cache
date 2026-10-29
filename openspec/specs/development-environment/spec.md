# development-environment Specification

## Purpose

This capability gives every contributor a reproducible local build, dependency, linting, and type-checking environment before feature work begins.

## Requirements

### Requirement: Contributors synchronize a locked uv project

The repository SHALL provide locked uv dependency metadata for reproducible local setup.

#### Scenario: A clean checkout is synchronized

- **WHEN** a contributor synchronizes all declared development groups with the locked command
- **THEN** the environment is created without changing the committed lockfile

### Requirement: Published dependencies exclude development tools

Published runtime dependencies SHALL remain separate from development tooling.

#### Scenario: A distribution is installed for runtime use

- **WHEN** a user installs the published package without contributor groups
- **THEN** development-only tools are not required as runtime dependencies

### Requirement: Published dependencies have no speculative upper bounds

Published runtime dependencies SHALL declare an upper bound only for a known, documented incompatibility.

#### Scenario: A dependency has no known incompatibility ceiling

- **WHEN** a supported runtime dependency has no documented incompatible release range
- **THEN** its published metadata does not exclude future releases merely because they do not exist yet

### Requirement: PyMongo minimum version has one source

The supported PyMongo lower bound SHALL be maintained only in published dependency metadata.

#### Scenario: The minimum PyMongo version is validated

- **WHEN** minimum-version validation resolves PyMongo
- **THEN** it reads the published lower bound without repeating a concrete version in tox, tests, or specifications

### Requirement: The project supports CPython 3.14 and newer

The project SHALL declare `requires-python = ">=3.14"` without a Python upper bound. Runnable examples SHALL declare the same minimum. `.python-version` SHALL select the exact default development interpreter, maintained by Renovate on stable releases without a repository release-line cap. CI SHALL exercise the earliest eligible patch, treating an omitted minimum patch as zero, and the exact selected development interpreter.

#### Scenario: Development advances to Python 3.15

- **WHEN** Renovate updates `.python-version` to a stable Python 3.15 release
- **THEN** development uses that exact release and CI validates Python 3.14.0 and the selected 3.15 release without raising the package minimum

#### Scenario: Development matches the exact package minimum

- **WHEN** the selected development interpreter equals the earliest eligible patch
- **THEN** CI runs one lane for that exact interpreter alongside any other supported release lines

#### Scenario: Development advances within the minimum release line

- **WHEN** development advances to another patch within Python 3.14
- **THEN** CI retains separate exact 3.14.0 and selected-development lanes

### Requirement: The source layout builds distributions

The project SHALL build installable distributions from `src/client_query_cache/` using `uv_build`'s default `src` module root.

#### Scenario: Source-layout distributions are built

- **WHEN** a contributor builds the project distribution
- **THEN** each resulting source and wheel distribution contains `client_query_cache` and imports
  successfully in a clean environment

### Requirement: The minimum supported PyMongo version is exercised

The contributor workflow SHALL validate the exact declared PyMongo lower bound independently of the lockfile, deriving it from published dependency metadata. It SHALL import `AsyncMongoClient` and exercise existing synchronous and asyncio collection-read, cursor, and bound-session tests against disposable MongoDB. A version mismatch, resolution error, or test failure SHALL fail validation. The check SHALL NOT change committed dependency metadata or the lockfile.

#### Scenario: The minimum PyMongo version is exercised

- **WHEN** the project validates its declared PyMongo lower bound
- **THEN** it confirms the installed driver equals that bound, imports `AsyncMongoClient`, and runs the supported behavioral checks successfully

#### Scenario: The lockfile advances independently

- **WHEN** the locked driver becomes newer without changing the published lower bound
- **THEN** minimum-version validation continues testing the exact declared minimum

#### Scenario: The minimum changes

- **WHEN** published metadata raises the PyMongo lower bound
- **THEN** minimum-version validation selects the new bound without another concrete driver pin

#### Scenario: The declared minimum cannot be exercised

- **WHEN** resolution fails, the installed version differs from the declared minimum, or a behavioral check fails
- **THEN** the contributor command fails visibly without silently substituting a newer driver

### Requirement: Local quality commands run complete checks

Contributors SHALL have documented commands that run the full local quality checks.

#### Scenario: A complete quality run finds a violation

- **WHEN** a contributor runs the documented full quality command on a violating tracked file
- **THEN** the responsible check reports the violation and the command fails

### Requirement: Local quality checks cover the declared tool set

The pinned Prek workflow SHALL check repository hygiene, formatting, linting, dead code, static types, slots, supported text formats, and secrets. Python hook environments SHALL retain the supported CPython 3.14 baseline independently of the development interpreter, using Prek's managed interpreter installation. Project packaging and test checks SHALL run across the CI compatibility matrix.

#### Scenario: A contributor runs all hooks

- **WHEN** the complete local quality workflow invokes Prek, including Ruff-extra
- **THEN** Python hooks use the supported CPython 3.14 baseline, while project checks use their selected development or compatibility-lane interpreter

### Requirement: Locked metadata is verified locally

Local quality checks SHALL detect when locked dependency metadata is out of date.

#### Scenario: The locked project is out of date

- **WHEN** a contributor runs the complete local quality workflow after changing dependency metadata without regenerating `uv.lock`
- **THEN** the `uv` locked-project validation reports the mismatch and the workflow fails

### Requirement: Quality tools exclude Git-submodule contents

Every formatter, validator, and linter provided by the repository SHALL exclude the working-tree
contents below the registered `specifications` Git submodule. This applies to hook-driven and
standalone quality commands, including commands that can write formatting fixes. The exclusion SHALL
preserve coverage of every repository-owned applicable file.

#### Scenario: A complete quality run encounters a submodule file

- **WHEN** a contributor runs the documented complete quality workflow with a Git submodule present
- **THEN** no formatter, validator, or linter reads, reports, or modifies files below that submodule

### Requirement: Contributors use a single command surface for setup and quality checks

The repository SHALL provide a `justfile` at the repository root with named recipes covering environment setup and every command in the complete local quality workflow. Documentation SHALL reference these recipes instead of the underlying multi-tool sequence.

#### Scenario: A contributor sets up the environment

- **WHEN** a contributor runs the documented setup recipe on a clean checkout inside the provisioned container image
- **THEN** it creates the locked `uv` environment, installs locked `npm` dependencies, and installs the repository's own hooks without any additional manual command, since the container image already provides `prek` and every other pinned toolchain tool the recipe itself does not install

#### Scenario: A contributor runs the complete quality workflow

- **WHEN** a contributor runs the documented quality recipe
- **THEN** it runs every check in the complete local quality workflow and fails if any check fails

### Requirement: The development container provides the documented toolchain

Contributors SHALL be able to build a development container with the documented toolchain. Rust builds SHALL use the stable release selected in the root rustup toolchain file. The image SHALL make that selection the default so Rust commands also work outside a checkout. Only that selected release is tested and supported. Fedora DNF packages SHALL be resolved from the selected Fedora release repositories, selecting the Node.js major track from the shared `.node-version`.

#### Scenario: A contributor builds the dev container image

- **WHEN** a contributor builds the container image from the documented definition
- **THEN** the resulting container has `gh`, `uv`, Node.js, npm, `prek`, `taplo`, `zizmor`, `just`, `rustc`, and `cargo` available on `PATH`, and Rust uses the selected toolchain as its default

#### Scenario: A contributor runs Rust outside a checkout

- **WHEN** a contributor invokes Rust commands from a directory without `rust-toolchain.toml`
- **THEN** rustup selects the image's default toolchain from the repository's pinned stable release

### Requirement: Container image inputs are pinned

The contributor image SHALL pin its base digest and tools installed outside DNF. DNF SHALL install `bash`, `gh`, `just`, `uv`, rustup, and Node.js/npm on the `.node-version` major track from Fedora 44 without RPM pins. Contributor documentation SHALL explain the bots' RPM pin limitations, expected low development-tool breakage risk, and package variability across rebuilds.

#### Scenario: A contributor rebuilds the image

- **WHEN** the same image definition is rebuilt
- **THEN** its base image and Rust toolchain remain pinned, DNF resolves compatible package versions from Fedora 44 repositories while selecting the Node.js major track from the shared `.node-version`, and host bridge commands remain documented host prerequisites

### Requirement: Container bootstrap states host prerequisites

The container workflow SHALL document rootless Podman, the selected `toolbox` or `distrobox` CLI, a systemd user session, and the host-execution bridge required by that container type.

#### Scenario: A Toolbx host lacks the Flatpak bridge

- **WHEN** a contributor uses Toolbx without `flatpak-spawn` and its portal or session-helper service
- **THEN** the guidance identifies that prerequisite and a dependent recipe fails with an actionable message

#### Scenario: A host cannot enable the rootless socket

- **WHEN** the host lacks `systemctl --user` for activating `podman.socket`
- **THEN** the documented workflow identifies the missing systemd user-session prerequisite

### Requirement: Immutable hosts can bootstrap the toolchain

The documented container workflow SHALL support contributors on immutable hosts.

#### Scenario: A contributor bootstraps from an immutable host

- **WHEN** a contributor follows the documented host bootstrap on Fedora Silverblue or another supported immutable host
- **THEN** the contributor builds and idempotently creates the development container with the host's existing Podman and container-frontend commands without installing `just` on the host

### Requirement: Container-backed tests use the host runtime

Tests inside the development container SHALL reach the host container runtime without a nested daemon.

#### Scenario: A contributor runs container-backed tests from inside the dev container

- **WHEN** a contributor runs the documented container-backed test recipe from inside the toolbx or Distrobox container
- **THEN** the test run connects to the host's Podman socket instead of starting a nested Podman daemon

#### Scenario: A contributor enables the host Podman socket from either container type

- **WHEN** a contributor runs the documented socket-enablement recipe from inside a toolbx container or a Distrobox container
- **THEN** the recipe enables the host's `podman.socket` through the container type's host-execution bridge and reports an actionable error if the forwarded socket path is not reachable afterward

#### Scenario: A contributor prepares full validation in a dev container

- **WHEN** a Toolbx or Distrobox contributor follows the documented full validation workflow
- **THEN** the guidance directs them to run `just enable-podman-socket` before `just tests_and_coverage`

### Requirement: Interactive Podman works in toolbx and Distrobox

Interactive Podman commands SHALL work from supported toolbx and Distrobox environments.

#### Scenario: A contributor issues an interactive Podman command from inside toolbx

- **WHEN** a contributor runs the documented Podman alias from inside the toolbx container
- **THEN** the command executes on the host instead of starting a nested Podman inside the toolbx

#### Scenario: A contributor issues an interactive Podman command from inside Distrobox

- **WHEN** a contributor runs the documented Podman alias from inside the Distrobox container
- **THEN** the command executes on the host via `distrobox-host-exec` instead of starting a nested Podman inside the Distrobox container

### Requirement: The generic test recipe accepts targeted arguments

The generic pytest recipe SHALL pass caller-supplied arguments through to pytest.

#### Scenario: A contributor runs targeted pytest arguments through the generic recipe

- **WHEN** a contributor runs the documented generic pytest-argument-forwarding recipe with custom arguments from inside the toolbx or Distrobox container
- **THEN** the invocation connects through the same forwarded Podman socket as the other container-backed test recipes

### Requirement: Tool configuration omits redundant defaults

Except for critical privileged CI pins meeting the exception below, repository-owned tool configuration and automation SHALL omit optional settings and command flags whose removal preserves effective behavior in every supported invocation context. Comparisons SHALL account for presets, wrappers, environment variables, and tool versions. Required fields, positional operands, and syntax delimiters are not optional overrides.

#### Scenario: A validation setting repeats a tool default

- **WHEN** an explicit link-validation setting equals the verified default and no inherited setting changes it
- **THEN** the setting is omitted and link validation remains enabled

#### Scenario: A preset changes the built-in default

- **WHEN** a local setting matches the built-in default but removing it activates a different inherited preset value
- **THEN** it is retained as an override of the inherited value

#### Scenario: A wrapper already supplies the behavior

- **WHEN** a command flag duplicates behavior supplied by its wrapper in every supported invocation
- **THEN** the redundant flag is omitted without changing standalone invocations that lack that wrapper

### Requirement: Behavioral overrides are distinguished from project inputs

A behavioral override changes meaningful policy supplied on omission, such as validation, failure handling, isolation, dependency policy, or resource limits. Ordinary declarative inputs, including navigation, paths, themes, enabled functionality/plugins, and content selection, SHALL require a rationale only when they counter inherited configuration or tool policy. Differing from an unset or fallback project input alone SHALL NOT make a setting a behavioral override.

#### Scenario: Ordinary project inputs are retained

- **WHEN** configuration supplies documentation directories, navigation, theme choices, plugin enablement, export sections, or tool input paths without countering inherited configuration or tool policy
- **THEN** those project inputs require no formal default-and-rationale explanation

#### Scenario: A declarative setting counters inherited policy

- **WHEN** a plugin setting re-enables validation disabled by an inherited preset
- **THEN** the setting is a behavioral override requiring a rationale for countering that inherited behavior

### Requirement: Every behavioral override has a specific rationale

Each retained behavioral override or critical privileged CI pin SHALL have a concise inline comment, documentation entry, or OpenSpec rationale identifying the option and concrete project need: `The default is <default_value>. We override it because <concise_rationale>.` Pins matching the default SHALL use `We keep it explicit` instead of `We override it`. Defaults SHALL follow the omitted-behavior requirement below; pins SHALL use their exception's locations.

#### Scenario: A command enables stricter validation

- **WHEN** an automation command retains a non-default strict-validation flag
- **THEN** an allowed location identifies the flag and explains its default and the required failure behavior using the specified sentence format

#### Scenario: A privileged CI setting pins the current default

- **WHEN** a retained setting matches the omitted value and qualifies for the critical privileged CI pin exception
- **THEN** its rationale uses `We keep it explicit because` to explain the pin without claiming to override that value

### Requirement: Default descriptions express omitted behavior

The default description SHALL state the behavior when the option is omitted in the applicable context. It SHALL use a concrete value when fixed, `unset` or `none` when no value is supplied, or a description of inheritance when context-dependent. Inheritance descriptions SHALL identify the configuration source and relevant context; they SHALL NOT imply a fixed value across environments.

#### Scenario: Git inherits user configuration

- **WHEN** an explicit signing setting protects a disposable repository from inherited Git configuration
- **THEN** its rationale describes the default as inherited from Git configuration, identifies the applicable configuration scope, and explains why signing is disabled

#### Scenario: Permissions depend on platform settings

- **WHEN** an explicit workflow permission setting constrains permissions inherited from repository or organization settings
- **THEN** its rationale describes that inheritance and the workflow context rather than claiming a universal omitted permission value

### Requirement: Default comparisons have authoritative evidence

Default-removal decisions and override explanations SHALL be supported by official documentation, schemas, source, or help for the applicable tool version and execution context. Evidence SHALL remain traceable after delivery from the retained explanation or, for removals, the implementation commit body. A guessed omitted behavior SHALL NOT justify removal or a factual rationale.

#### Scenario: Documentation describes another release

- **WHEN** current upstream documentation disagrees with the repository's selected tool version
- **THEN** the audit uses evidence for the selected version and records the discrepancy before changing the setting

#### Scenario: Omitted behavior cannot be established

- **WHEN** authoritative evidence establishes neither a fixed omitted value nor the applicable inheritance behavior
- **THEN** the audit reports a completion blocker instead of inventing omitted behavior or silently excluding the option

#### Scenario: Removal evidence survives ledger disposal

- **WHEN** implementation removes a redundant setting or flag and its temporary audit ledger is no longer available
- **THEN** the implementation commit body identifies the affected occurrence, supplied value, omitted behavior, authoritative source, tool version, and execution context, grouping occurrences only when their evidence and context agree

### Requirement: Override explanations remain traceable and current

An explanation SHALL map unambiguously to every option or flag it covers. Shared explanations SHALL enumerate covered occurrences and apply only when default, context, and rationale agree. Edits to an override SHALL recheck its default and remove explanations for deleted overrides. Dependency-update automation SHALL NOT be presumed to perform semantic audits of upstream defaults.

#### Scenario: Several commands share a justified flag

- **WHEN** one documentation entry explains the same override across multiple commands
- **THEN** it identifies those commands and covers each occurrence without duplicating the rationale

#### Scenario: Maintenance identifies a redundant override

- **WHEN** maintenance establishes that a retained override equals the installed tool's effective default
- **THEN** the redundant setting and its obsolete explanation are removed unless the setting meets the critical privileged CI pin exception

### Requirement: Integration tests guard required upstream behavior

When default cleanup relies on unstable upstream behavior for a required repository contract, integration tests SHALL exercise that contract through the real tool with the redundant settings omitted. Tests SHALL verify observable success and failure behavior rather than default values or configuration text. Applicable dependency updates SHALL run these tests before automatic acceptance. Anticipated default drift alone SHALL NOT justify restating a default.

#### Scenario: An upstream upgrade disables link validation by default

- **WHEN** an updated documentation tool accepts a missing local page or heading target with redundant validation settings omitted
- **THEN** integration tests expecting strict-build failure fail and prevent successful dependency-update validation

#### Scenario: Valid documentation still builds

- **WHEN** valid documentation is built through the same configuration and invocation path
- **THEN** integration tests require the build to succeed, so an unrelated persistent build failure cannot satisfy the invalid-input cases

### Requirement: Critical privileged CI pins have a narrow exception

An explicit default MAY remain only to protect a critical security or production-safety contract in privileged CI when safe real-behavior integration tests cannot adequately cover it. An inline comment or OpenSpec specification SHALL give the pin rationale, naming the protected contract, concrete harm, and why safe testing is insufficient. The pin SHALL have authoritative default evidence. Convenience, ordinary CI settings, or hypothetical drift alone SHALL NOT qualify.

#### Scenario: A privileged action cannot be safely exercised

- **WHEN** a setting matching the current default protects a critical credential or publication boundary and safe integration testing cannot adequately cover that behavior
- **THEN** the setting remains explicit with an inline or OpenSpec rationale satisfying every exception condition

#### Scenario: A critical behavior has safe test coverage

- **WHEN** a safe real-behavior integration test adequately covers the critical contract with the redundant setting omitted
- **THEN** the normal omission rule applies and the dependency update runs that test

#### Scenario: Neither coverage nor an exception is justified

- **WHEN** a contract-relevant removal lacks required safe integration coverage and the setting does not qualify for the exception
- **THEN** that removal remains blocked rather than weakening the contract or silently claiming a permanent pin exception

### Requirement: Default cleanup preserves repository contracts

Default cleanup SHALL preserve existing validation coverage, failure propagation, dependency-update ownership and policy, reproducibility, credential isolation, and supported invocation contexts. It SHALL NOT weaken a contract to make a setting removable.

#### Scenario: An apparent default has execution consequences

- **WHEN** removing a shell selection, action input, or inherited override changes error handling, trust boundaries, or supported environment behavior
- **THEN** the necessary setting remains and receives its override rationale

### Requirement: Override rationales stay with their configuration

Rationales for commentable options and commands SHALL live beside them or in a shared comment block within their owning file. Command examples SHALL keep their explanations beside the example in the same guide. Formats without comments SHALL use existing contributor documentation. A separate cross-file inventory SHALL NOT be used for rationale placement.

#### Scenario: A single command clears inherited configuration

- **WHEN** an automation command clears an inherited environment variable
- **THEN** its rationale appears beside that command rather than in a separate option inventory

#### Scenario: Strict JSON needs an explanation

- **WHEN** a strict-JSON configuration retains a behavioral override
- **THEN** existing contributor documentation identifies that override and its rationale without adding comment fields to the JSON

### Requirement: In-repository native extensions build from locked sources

Synchronizing the development groups SHALL build every in-repository native extension from its committed sources and crate lockfile. A missing compiler toolchain SHALL fail synchronization visibly, and contributor documentation SHALL name the required toolchain with a reference to its official installation guide.

#### Scenario: A clean checkout is synchronized with Rust installed

- **WHEN** a contributor with the documented toolchain synchronizes all development groups using the locked command
- **THEN** the native extension is built from the committed crate lockfile and importable in the project environment, and the lockfiles are unchanged

#### Scenario: The compiler toolchain is missing

- **WHEN** a contributor without Cargo synchronizes the development groups
- **THEN** synchronization fails with an error naming the missing build tool

### Requirement: Public integrity digests do not create secret findings

The secret scanner SHALL use its built-in line-exclusion filter for exact JSON `binary_sha256` and `cargo_lock_sha256` fields containing 64 lowercase hexadecimal characters. These public reproducibility digests SHALL NOT require repeated per-report baseline entries. Other fields and scanner rules SHALL retain their existing checks.

#### Scenario: A registered environment records its build digests

- **WHEN** an environment JSON records a native binary or Cargo lockfile digest in the named fields
- **THEN** secret scanning excludes those exact digest lines and continues checking other content

### Requirement: Declared Python release lines drive compatibility coverage

Package metadata SHALL list Python 3.14 and 3.15 version classifiers. CI SHALL cover every release line from the minimum through the highest classified or selected development line, even when development uses an older line. Lines represented by the exact minimum or development requests SHALL need no additional floating request; remaining lines SHALL use major/minor requests. Only identical emitted requests SHALL be deduplicated.

#### Scenario: Python 3.15 is tested before development advances

- **WHEN** metadata lists Python 3.14 and 3.15 and development selects 3.14.6
- **THEN** CI emits `3.14.0`, `3.15`, and `3.14.6`

#### Scenario: Development advances beyond the classified lines

- **WHEN** development selects 3.16.0 while metadata lists Python 3.14 and 3.15
- **THEN** CI emits `3.14.0`, `3.15`, and `3.16.0`

#### Scenario: Python 3.15 has only a downloadable release candidate

- **WHEN** the CI toolchain provides a Python 3.15 release candidate and no stable 3.15 download
- **THEN** the 3.15 lane runs on that candidate without changing the stable development selection

#### Scenario: Stable Python 3.15 becomes downloadable

- **WHEN** the CI toolchain provides a stable 3.15 download on a fresh runner
- **THEN** the 3.15 request selects a stable interpreter without retaining a separate release-candidate lane

### Requirement: Native formatting is enforced

The local quality workflow SHALL reject Rust source that differs from the standard formatter. The formatting recipe SHALL repair those differences.

#### Scenario: Rust formatting differs

- **WHEN** a contributor checks an incorrectly formatted native source file
- **THEN** the quality command fails and the formatting command repairs the file

### Requirement: Native compiler and lint diagnostics fail validation

The native lint command SHALL reject compiler and Clippy warnings in the production Python-extension configuration and the concurrency-model configuration. Production dead-code and unused-import diagnostics SHALL NOT be suppressed wholesale. Configuration-specific exceptions SHALL state their reason beside the suppression.

#### Scenario: Unused production code is introduced

- **WHEN** a private unused function is added to the native extension
- **THEN** native linting fails

### Requirement: Native dependency policy is enforced

The local native quality workflow SHALL reject unused dependencies and unlinked Rust files, known dependency vulnerabilities, disallowed licenses, unapproved dependency sources, and duplicate dependency versions. Dependency-policy warnings SHALL fail validation.

#### Scenario: A dependency violates policy

- **WHEN** the native dependency graph violates the configured policy
- **THEN** native quality validation reports the violation and exits unsuccessfully

### Requirement: Stable Rust toolchain updates are reviewed

Development, CI and release builds SHALL use the root selected stable Rust toolchain. Dependabot SHALL check weekly for stable releases, including patches, and toolchain update pull requests SHALL require human acceptance after validation.

#### Scenario: A stable Rust release is published

- **WHEN** Dependabot checks the root versioned toolchain after a stable release is available
- **THEN** it can propose an update without changing the Cargo dependency schedule

#### Scenario: The toolchain selection changes

- **WHEN** a pull request changes the root toolchain file
- **THEN** CI selects Rust, Python extension, contributor image and ARM64 validation and does not automatically accept the update

### Requirement: Rust quality components are separate from source builds

The root `rust-toolchain.toml` SHALL select the minimal rustup profile. Native quality setup SHALL install rustfmt, Clippy, and LLVM coverage components separately.

#### Scenario: A source distribution is built

- **WHEN** rustup reads the toolchain file while building the Python source distribution
- **THEN** it installs the compiler, standard library, and Cargo without installing development-only quality components

#### Scenario: Native quality checks are prepared

- **WHEN** a contributor runs `just setup-rust`
- **THEN** rustfmt, Clippy, and LLVM coverage components are available for the native quality checks

### Requirement: CI installs Rust only for native consumers

The shared CI toolchain action SHALL install the root Rust selection only when a calling job builds or checks native code.

#### Scenario: A non-native CI job sets up the shared toolchain

- **WHEN** a documentation or Prek job uses the shared CI toolchain action
- **THEN** it provisions uv and just without installing Rust

#### Scenario: A native CI job sets up the shared toolchain

- **WHEN** a CI job builds or checks native code and requests Rust setup
- **THEN** it installs the Rust release selected by the root toolchain file
