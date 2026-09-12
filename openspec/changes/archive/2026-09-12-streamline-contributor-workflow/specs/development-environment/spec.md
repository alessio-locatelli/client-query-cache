## MODIFIED Requirements

### Requirement: Container-based contributors reach a container runtime without nesting

Contributors working inside a toolbx or Distrobox container SHALL enable and reach the host's
rootless Podman runtime through a documented host-execution bridge (`flatpak-spawn --host` for
toolbx, `distrobox-host-exec` for Distrobox), both for the one-time host `podman.socket` enablement
and for interactive Podman CLI use. This requires a host with a systemd user session
(`systemctl --user`, which manages `podman.socket`'s activation); the repository SHALL document that
alongside the other host prerequisites rather than implying the workflow supports non-systemd hosts.
The toolbx path additionally requires the Flatpak host-execution bridge (`flatpak-spawn`, backed by
the Flatpak portal/session-helper D-Bus service) to already be present - a bare "Podman plus the
`toolbox` CLI" host does not guarantee it - so the repository SHALL document it as an explicit
toolbx-path prerequisite rather than assuming every Toolbox installation provides it. Docker-API
clients (e.g. Testcontainers) SHALL connect to that forwarded Podman socket. Contributors SHALL NOT
run a second Podman daemon nested inside the contributor container, because the container's shared
home-directory mount lets a nested daemon corrupt the host's own Podman state. Contributor guidance
SHALL identify `just enable-podman-socket` as required before the documented full test-and-coverage
command in a Toolbx or Distrobox container, while distinguishing the container-free unit command.

#### Scenario: A contributor runs container-backed tests from inside the dev container

- **WHEN** a contributor runs the documented container-backed test recipe from inside the toolbx or
  Distrobox container
- **THEN** the test run connects to the host's Podman socket instead of starting a nested Podman
  daemon

#### Scenario: A contributor enables the host Podman socket from either container type

- **WHEN** a contributor runs the documented socket-enablement recipe from inside a toolbx container
  or a Distrobox container
- **THEN** the recipe enables the host's `podman.socket` through the container type's host-execution
  bridge and reports an actionable error if the forwarded socket path is not reachable afterward

#### Scenario: A contributor prepares full validation in a dev container

- **WHEN** a Toolbx or Distrobox contributor follows the documented full validation workflow
- **THEN** the guidance directs them to run `just enable-podman-socket` before `just coverage`

#### Scenario: A contributor issues an interactive Podman command from inside toolbx

- **WHEN** a contributor runs the documented Podman alias from inside the toolbx container
- **THEN** the command executes on the host instead of starting a nested Podman inside the toolbx

#### Scenario: A contributor issues an interactive Podman command from inside Distrobox

- **WHEN** a contributor runs the documented Podman alias from inside the Distrobox container
- **THEN** the command executes on the host via `distrobox-host-exec` instead of starting a nested
  Podman inside the Distrobox container
