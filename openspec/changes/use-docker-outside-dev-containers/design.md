## Context

`scripts/testcontainers-bridge.sh` is sourced by every container-backed recipe. It points
Testcontainers at the host's rootless Podman socket inside Toolbx and Distrobox, returns without
configuration on GitHub Actions, and exits with an error everywhere else.

## Decisions

### D1: Outside Toolbx and Distrobox, leave the Docker endpoint to the caller

The bridge configures Testcontainers only inside Toolbx and Distrobox. Elsewhere it exports nothing,
so Testcontainers discovers the endpoint itself: `DOCKER_HOST` when set, otherwise the default
Docker socket. No probe is needed: the existing MongoDB fixture already reports an unreachable
runtime (delta spec scenario "No container runtime is reachable outside Toolbx and Distrobox").

Alternatives:

- **Probe for a Docker socket in the bridge and fail when none is reachable.** Pro: fails before
  `uv run` starts. Con: duplicates Testcontainers' endpoint discovery, rejects valid `DOCKER_HOST`
  values that the probe does not understand, and repeats the fixture's actionable error. Rejected.
- **Recognize Claude Code cloud sessions specifically.** Pro: no behavior change for other
  environments. Con: couples the recipes to one vendor's environment markers, and other Linux
  environments with Docker remain refused for no technical reason. Rejected.
- **Set `GITHUB_ACTIONS=true` in the cloud environment.** Pro: no repository change. Con: recipes
  and benchmarks read that variable to emit workflow commands, lower log levels, and classify runs
  as CI, so local runs would be misreported. Rejected.
- **Support Distrobox on a Docker host.** Not needed for the goal: the cloud environment has no
  Distrobox, and the Distrobox branch keeps assuming the host's rootless Podman. No contributor
  needs it; no follow-up is planned.

Unknowns: none. The fallback was exercised in a Claude Code cloud session by running the unit tier
and a MongoDB-backed test file against its Docker daemon.

### D2: The GitHub Actions special case is subsumed

GitHub Actions runners have neither the Toolbx marker nor `distrobox-host-exec`, so they take the D1
fallback and export the same (empty) configuration as before. The separate `GITHUB_ACTIONS` check is
removed, and `TESTCONTAINERS_RYUK_PRIVILEGED` is exported only on the Podman paths that need it.

Alternative: keep the explicit check. Pro: none, because both paths behave identically. Con: an
extra branch with no effect. Rejected. Unknowns: none.

## Risks

A contributor on a host without Toolbx or Distrobox who expected the bridge to refuse can now run
container-backed recipes against whichever runtime their environment exposes. The toolchain
requirements are unchanged: such an environment must still provide the declared tools.
