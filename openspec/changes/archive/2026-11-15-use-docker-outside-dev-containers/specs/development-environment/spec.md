## MODIFIED Requirements

### Requirement: Container-backed tests use the host runtime

Tests inside the development container SHALL reach the host container runtime without a nested daemon. Outside Toolbx and Distrobox, container-backed recipes SHALL use the caller's Docker endpoint, as selected by `DOCKER_HOST` or the default Docker socket, instead of refusing to run.

#### Scenario: A contributor runs container-backed tests from inside the dev container

- **WHEN** a contributor runs the documented container-backed test recipe from inside the toolbx or Distrobox container
- **THEN** the test run connects to the host's Podman socket instead of starting a nested Podman daemon

#### Scenario: A contributor runs container-backed tests outside Toolbx and Distrobox

- **WHEN** a contributor runs a documented container-backed test recipe in an environment that provides the declared toolchain and a running Docker daemon but no Toolbx or Distrobox, such as GitHub Actions or a hosted Linux development container
- **THEN** the test run starts its disposable MongoDB through that Docker daemon

#### Scenario: No container runtime is reachable outside Toolbx and Distrobox

- **WHEN** a contributor runs a documented container-backed test recipe outside Toolbx and Distrobox without a reachable Docker endpoint
- **THEN** the run fails with a message asking the contributor to start a Docker-compatible container runtime

#### Scenario: A contributor enables the host Podman socket from either container type

- **WHEN** a contributor runs the documented socket-enablement recipe from inside a toolbx container or a Distrobox container
- **THEN** the recipe enables the host's `podman.socket` through the container type's host-execution bridge and reports an actionable error if the forwarded socket path is not reachable afterward

#### Scenario: A contributor prepares full validation in a dev container

- **WHEN** a Toolbx or Distrobox contributor follows the documented full validation workflow
- **THEN** the guidance directs them to run `just enable-podman-socket` before `just tests_and_coverage`
