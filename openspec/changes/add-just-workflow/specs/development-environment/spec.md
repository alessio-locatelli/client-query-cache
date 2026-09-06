## ADDED Requirements

### Requirement: Contributors use a single command surface for setup and quality checks

The repository SHALL provide a `justfile` at the repository root with named recipes covering environment setup and every command in the complete local quality workflow. Documentation SHALL reference these recipes instead of the underlying multi-tool sequence.

#### Scenario: A contributor sets up the environment

- **WHEN** a contributor runs the documented setup recipe on a clean checkout inside the provisioned container image
- **THEN** it creates the locked `uv` environment, installs locked `npm` dependencies, and installs the repository's own hooks without any additional manual command, since the container image already provides `prek` and every other pinned toolchain tool the recipe itself does not install

#### Scenario: A contributor runs the complete quality workflow

- **WHEN** a contributor runs the documented quality recipe
- **THEN** it runs every check in the complete local quality workflow and fails if any check fails

### Requirement: Contributors get a reproducible container-based toolchain

The repository SHALL provide a container image definition declaring the pinned contributor toolchain (Python 3.14 via `uv`, Node.js, npm, `prek`, `taplo`, `zizmor`, and `just` itself), buildable and usable as a toolbx or Distrobox container image on any Linux host with rootless Podman and the corresponding `toolbox` or `distrobox` CLI installed, since Podman alone does not provide either container frontend. Every declared tool SHALL be pinned to an explicit version, and the base image SHALL be pinned to an exact digest rather than a tag, so that rebuilding the image from the same definition reproduces the same toolchain. The image SHALL provide every in-container tool a documented `just` recipe depends on; a recipe SHALL NOT depend on an in-container tool that is undefined or unpinned in the image. This pinning obligation does NOT extend to the host itself or to the host-execution bridge (`flatpak-spawn`, `distrobox-host-exec`) and the host commands reached through it (`podman`, `systemctl --user`), since those run outside the image by design; recipes that depend on them SHALL document the host prerequisite instead and SHALL fail with an actionable message when it is unavailable.

#### Scenario: A contributor builds the dev container image

- **WHEN** a contributor builds the container image from the documented definition
- **THEN** the resulting container has `uv`, Node.js, npm, `prek`, `taplo`, `zizmor`, and `just` available on `PATH`, each at the pinned version, without further manual installation

### Requirement: Container-based contributors reach a container runtime without nesting

Contributors working inside a toolbx or Distrobox container SHALL enable and reach the host's rootless Podman runtime through a documented host-execution bridge (`flatpak-spawn --host` for toolbx, `distrobox-host-exec` for Distrobox), both for the one-time host `podman.socket` enablement and for interactive Podman CLI use. This requires a host with a systemd user session (`systemctl --user`, which manages `podman.socket`'s activation); the repository SHALL document that alongside the other host prerequisites rather than implying the workflow supports non-systemd hosts. The toolbx path additionally requires the Flatpak host-execution bridge (`flatpak-spawn`, backed by the Flatpak portal/session-helper D-Bus service) to already be present - a bare "Podman plus the `toolbox` CLI" host does not guarantee it - so the repository SHALL document it as an explicit toolbx-path prerequisite rather than assuming every Toolbox installation provides it. Docker-API clients (e.g. Testcontainers) SHALL connect to that forwarded Podman socket. Contributors SHALL NOT run a second Podman daemon nested inside the contributor container, because the container's shared home-directory mount lets a nested daemon corrupt the host's own Podman state.

#### Scenario: A contributor runs container-backed tests from inside the dev container

- **WHEN** a contributor runs the documented container-backed test recipe from inside the toolbx or Distrobox container
- **THEN** the test run connects to the host's Podman socket instead of starting a nested Podman daemon

#### Scenario: A contributor enables the host Podman socket from either container type

- **WHEN** a contributor runs the documented socket-enablement recipe from inside a toolbx container or a Distrobox container
- **THEN** the recipe enables the host's `podman.socket` through the container type's host-execution bridge and reports an actionable error if the forwarded socket path is not reachable afterward

#### Scenario: A contributor issues an interactive Podman command from inside toolbx

- **WHEN** a contributor runs the documented Podman alias from inside the toolbx container
- **THEN** the command executes on the host instead of starting a nested Podman inside the toolbx

#### Scenario: A contributor issues an interactive Podman command from inside Distrobox

- **WHEN** a contributor runs the documented Podman alias from inside the Distrobox container
- **THEN** the command executes on the host via `distrobox-host-exec` instead of starting a nested Podman inside the Distrobox container
