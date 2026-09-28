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

The project's declared Python compatibility SHALL include CPython 3.14 and newer.

#### Scenario: A contributor selects the baseline interpreter

- **WHEN** the locked project and quality tools run on CPython 3.14
- **THEN** they use the supported package baseline

### Requirement: The source layout builds distributions

The project SHALL build installable distributions from `src/client_query_cache/` using `uv_build` with `module-root = "src"`.

#### Scenario: Source-layout distributions are built

- **WHEN** a contributor builds the project distribution
- **THEN** each resulting source and wheel distribution contains `client_query_cache` and imports
  successfully in a clean environment

### Requirement: The minimum supported PyMongo version is exercised

The contributor workflow SHALL validate the minimum supported PyMongo version.

#### Scenario: The minimum PyMongo version is exercised

- **WHEN** the project validates its declared PyMongo lower bound
- **THEN** it resolves the lower bound from the published dependency metadata, imports
  `AsyncMongoClient`, and runs the supported minimum-version checks successfully

### Requirement: Local quality commands run complete checks

Contributors SHALL have documented commands that run the full local quality checks.

#### Scenario: A complete quality run finds a violation

- **WHEN** a contributor runs the documented full quality command on a violating tracked file
- **THEN** the responsible check reports the violation and the command fails

### Requirement: Local quality checks cover the declared tool set

The pinned Prek workflow SHALL check repository hygiene, formatting, linting, dead code, static types, slots, supported text formats, and secrets under the CPython 3.14 package baseline.

#### Scenario: A contributor runs all hooks

- **WHEN** the complete local quality workflow invokes Prek, including Ruff-extra
- **THEN** every declared check uses the CPython 3.14 package baseline

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

### Requirement: The development container builds reproducibly

Contributors SHALL be able to build a development container with the documented toolchain.

#### Scenario: A contributor builds the dev container image

- **WHEN** a contributor builds the container image from the documented definition
- **THEN** the resulting container has `uv`, Node.js, npm, `prek`, `taplo`, `zizmor`, and `just` available on `PATH`, each at the pinned version, without further manual installation

### Requirement: Container image inputs are pinned

The contributor image SHALL pin its base image by exact digest and every in-container tool used by a documented recipe to an explicit version.

#### Scenario: A contributor rebuilds the image

- **WHEN** the same image definition is rebuilt
- **THEN** its base image and in-container tool versions remain fixed, while host bridge commands are treated as documented host prerequisites

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
