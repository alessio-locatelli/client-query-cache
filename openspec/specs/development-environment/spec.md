# development-environment Specification

## Purpose

This capability gives every contributor a reproducible local build, dependency, linting, and type-checking environment before feature work begins.

## Requirements

### Requirement: Contributors use a locked uv project

The repository SHALL use `uv` for dependency resolution, environments, and package builds, SHALL
configure `uv_build` with `module-root = "src"` for the
`src/client_query_cache/` package, SHALL commit `uv.lock`, and SHALL support CPython 3.14+. Its
published PyMongo dependency SHALL declare the lower bound required for the supported native async
API. The declared dependency metadata SHALL be the sole maintained source of that concrete lower
bound: the minimum-version validation SHALL resolve and exercise it without repeating a version in
tox, tests, or specifications. Published runtime dependencies SHALL NOT declare a speculative upper
bound: a dependency floor SHALL exclude only versions with a known, documented incompatibility,
never versions that merely do not exist yet, per [the standard guidance against pinning a library's
dependency ceiling](https://iscinumpy.dev/post/bound-version-constraints/#pinning-the-python-version-is-special).
Published runtime dependencies SHALL remain distinct from development tooling.

#### Scenario: A clean checkout is synchronized

- **WHEN** a contributor synchronizes all declared development groups with the locked command
- **THEN** the environment is created without changing the committed lockfile

#### Scenario: Source-layout distributions are built

- **WHEN** a contributor builds the project distribution
- **THEN** each resulting source and wheel distribution contains `client_query_cache` and imports
  successfully in a clean environment

#### Scenario: The minimum PyMongo version is exercised

- **WHEN** the project validates its declared PyMongo lower bound
- **THEN** it resolves the lower bound from the published dependency metadata, imports
  `AsyncMongoClient`, and runs the supported minimum-version checks successfully

### Requirement: Contributors can run complete local quality checks

The repository SHALL provide a pinned Prek configuration that checks repository hygiene, formatting, linting, dead code, static types, slots, supported text formats, and secrets. The configuration SHALL run every check, including Ruff-extra, under the CPython 3.14 package baseline. The complete local quality workflow SHALL also validate `pyproject.toml` and the committed `uv.lock` with equivalent `uv` locked-project checks in place of the existing Poetry-specific project check, without passing matched filenames to a filename-insensitive `uv` command.

#### Scenario: A complete quality run finds a violation

- **WHEN** a contributor runs the documented full quality command on a violating tracked file
- **THEN** the responsible check reports the violation and the command fails

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

### Requirement: Contributors get a reproducible container-based toolchain

The repository SHALL provide a container image definition declaring the pinned contributor toolchain (Python 3.14 via `uv`, Node.js, npm, `prek`, `taplo`, `zizmor`, and `just` itself), buildable and usable as a toolbx or Distrobox container image on any Linux host with rootless Podman and the corresponding `toolbox` or `distrobox` CLI installed, since Podman alone does not provide either container frontend. Every declared tool SHALL be pinned to an explicit version, and the base image SHALL be pinned to an exact digest rather than a tag, so that rebuilding the image from the same definition reproduces the same toolchain. The initial host bootstrap SHALL use Podman and the selected container frontend directly and SHALL NOT require `just` on the host. The image SHALL provide every in-container tool a documented `just` recipe depends on; a recipe SHALL NOT depend on an in-container tool that is undefined or unpinned in the image. This pinning obligation does NOT extend to the host itself or to the host-execution bridge (`flatpak-spawn`, `distrobox-host-exec`) and the host commands reached through it (`podman`, `systemctl --user`), since those run outside the image by design; recipes that depend on them SHALL document the host prerequisite instead and SHALL fail with an actionable message when it is unavailable.

#### Scenario: A contributor builds the dev container image

- **WHEN** a contributor builds the container image from the documented definition
- **THEN** the resulting container has `uv`, Node.js, npm, `prek`, `taplo`, `zizmor`, and `just` available on `PATH`, each at the pinned version, without further manual installation

#### Scenario: A contributor bootstraps from an immutable host

- **WHEN** a contributor follows the documented host bootstrap on Fedora Silverblue or another supported immutable host
- **THEN** the contributor builds and idempotently creates the development container with the host's existing Podman and container-frontend commands without installing `just` on the host

### Requirement: Container-based contributors reach a container runtime without nesting

Contributors working inside a toolbx or Distrobox container SHALL enable and reach the host's rootless Podman runtime through a documented host-execution bridge (`flatpak-spawn --host` for toolbx, `distrobox-host-exec` for Distrobox), both for the one-time host `podman.socket` enablement and for interactive Podman CLI use. This requires a host with a systemd user session (`systemctl --user`, which manages `podman.socket`'s activation); the repository SHALL document that alongside the other host prerequisites rather than implying the workflow supports non-systemd hosts. The toolbx path additionally requires the Flatpak host-execution bridge (`flatpak-spawn`, backed by the Flatpak portal/session-helper D-Bus service) to already be present - a bare "Podman plus the `toolbox` CLI" host does not guarantee it - so the repository SHALL document it as an explicit toolbx-path prerequisite rather than assuming every Toolbox installation provides it. Docker-API clients (e.g. Testcontainers) SHALL connect to that forwarded Podman socket. Contributors SHALL NOT run a second Podman daemon nested inside the contributor container, because the container's shared home-directory mount lets a nested daemon corrupt the host's own Podman state. Contributor guidance SHALL identify `just enable-podman-socket` as required before the documented full test-and-coverage command in a Toolbx or Distrobox container, while distinguishing the container-free unit command. Every documented container-backed test entry point, including a generic pytest-argument-forwarding recipe, SHALL reach the host runtime through this same bridge rather than repeating a separate, divergent connection method.

#### Scenario: A contributor runs container-backed tests from inside the dev container

- **WHEN** a contributor runs the documented container-backed test recipe from inside the toolbx or Distrobox container
- **THEN** the test run connects to the host's Podman socket instead of starting a nested Podman daemon

#### Scenario: A contributor enables the host Podman socket from either container type

- **WHEN** a contributor runs the documented socket-enablement recipe from inside a toolbx container or a Distrobox container
- **THEN** the recipe enables the host's `podman.socket` through the container type's host-execution bridge and reports an actionable error if the forwarded socket path is not reachable afterward

#### Scenario: A contributor prepares full validation in a dev container

- **WHEN** a Toolbx or Distrobox contributor follows the documented full validation workflow
- **THEN** the guidance directs them to run `just enable-podman-socket` before `just tests_and_coverage`

#### Scenario: A contributor issues an interactive Podman command from inside toolbx

- **WHEN** a contributor runs the documented Podman alias from inside the toolbx container
- **THEN** the command executes on the host instead of starting a nested Podman inside the toolbx

#### Scenario: A contributor issues an interactive Podman command from inside Distrobox

- **WHEN** a contributor runs the documented Podman alias from inside the Distrobox container
- **THEN** the command executes on the host via `distrobox-host-exec` instead of starting a nested Podman inside the Distrobox container

#### Scenario: A contributor runs targeted pytest arguments through the generic recipe

- **WHEN** a contributor runs the documented generic pytest-argument-forwarding recipe with custom arguments from inside the toolbx or Distrobox container
- **THEN** the invocation connects through the same forwarded Podman socket as the other container-backed test recipes
