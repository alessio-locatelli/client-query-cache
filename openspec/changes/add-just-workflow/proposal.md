## Why

Contributor setup and daily commands are currently a flat list of separate CLI invocations in `AGENTS.md` (`uv`, `prek`, `ruff`, `mypy`, `taplo`, `npm`) with no automation, and none of it accounts for working from inside a rootless Podman container (toolbx or Distrobox) on an immutable host such as Fedora Silverblue, which is how this project's development is actually done. Contributors need one documented, low-friction path to a working environment and a single command surface to run it, regardless of host.

## What Changes

- Add a `justfile` at the repository root exposing named recipes for every setup and quality-check command currently listed in `AGENTS.md`, so contributors run one verb (`just setup`, `just lint`, `just test`) instead of memorizing a multi-tool sequence.
- Add a `Containerfile` defining the pinned contributor toolchain (Python 3.14 via `uv`, Node.js/npm, `prek`, `taplo`) so a toolbx or Distrobox container can be built and created from it on any Linux host, instead of each contributor installing tools ad hoc.
- Document how that container reaches a container runtime for Testcontainers-backed tests without nesting Podman inside itself: forward the host's rootless `podman.socket` for the Docker-API clients that need it, and alias interactive `podman` CLI use to `flatpak-spawn --host podman` (toolbx) or the native passthrough (Distrobox). Nesting a second Podman daemon inside the contributor container is explicitly out because it can corrupt the host's `~/.config/containers` state through the shared home-directory mount.
- Update `AGENTS.md` command references to point at the `just` recipes instead of the raw multi-tool sequence. `README.md` currently has no setup or command instructions to replace; it gets at most a one-line pointer to the contributor setup docs, since implementation-level mechanics (toolbx, Podman sockets, task runners) don't belong in a user-facing README.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `development-environment`: adds a `just`-driven command surface and a container-image-based contributor bootstrap (toolbx/Distrobox), including documented, non-nested container-runtime access for the tools that need it.

## Impact

- Affected: repository root (`justfile`, `Containerfile`), `AGENTS.md`, `README.md`.
- Depends on `bootstrap-test-environment` being applied first: the `test`/`coverage`/`test-integration`/`test-e2e` recipes select its unit/integration/end-to-end pytest markers by name, and the container-backed recipes drive its Testcontainers fixture over the forwarded Podman socket. This change does not redefine test-tier semantics; it wraps what `bootstrap-test-environment` already establishes. It does not add a `benchmark` recipe: `benchmark-change-stream-costs` owns that marker's invocation when it lands, since no cache implementation exists yet to benchmark.
- No production code, published dependencies, or runtime behavior changes.
