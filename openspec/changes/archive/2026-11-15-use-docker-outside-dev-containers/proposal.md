## Why

Container-backed recipes refuse to run anywhere except Toolbx, Distrobox, or GitHub Actions. Claude
Code cloud sessions run in a Linux container that provides the declared toolchain and a Docker
daemon, but no Toolbx or Distrobox, so `just pytest`, `just tests_and_coverage`, and the other
MongoDB-backed recipes cannot run there although the runtime they need is available.

## What Changes

- Outside Toolbx and Distrobox, container-backed recipes use the caller's Docker endpoint instead of
  refusing to run.
- The contributor guide states how container-backed recipes reach a runtime outside Toolbx and
  Distrobox.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `development-environment`: container-backed recipes outside Toolbx and Distrobox.

## Impact

- `scripts/testcontainers-bridge.sh` and `CONTRIBUTING.md`.
- No package, CI workflow, Toolbx, or Distrobox behavior changes.
