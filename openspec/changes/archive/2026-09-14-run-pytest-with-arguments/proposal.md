## Why

Contributors and coding agents regularly need to run pytest with custom arguments — a specific file
or node ID, `-k`, `--pdb`, and similar — but every documented test recipe (`test-integration`,
`test-e2e`, `coverage`) only runs a fixed marker selection. `CONTRIBUTING.md` currently tells
contributors to "use pytest directly" for that case, which means manually reproducing the
Toolbx/Distrobox container-runtime bridge (`DOCKER_HOST`, `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE`,
`TESTCONTAINERS_RYUK_PRIVILEGED`) that those recipes already set up internally, by hand, on every
invocation. Separately, the existing `test` recipe (`uv run -- pytest -m unit`) adds no behavior
over typing that command directly and its name does not communicate that it is unit-only, so it is
worth removing while touching this area.

## What Changes

- Add a `pytest *args:` recipe (invoked as `just pytest -- <args>`) that forwards arbitrary
  arguments to `pytest` through `uv run`, applying the same Toolbx/Distrobox/CI container-runtime
  bridge that `test-integration`, `test-e2e`, and `coverage` already use, so ad hoc and
  targeted runs no longer need manual environment exports.
- Extract the bridge-detection and export logic (Toolbx/Distrobox detection, `DOCKER_HOST`,
  `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE`, `TESTCONTAINERS_RYUK_PRIVILEGED`, and the actionable
  `exit 1` guidance) out of `test-integration`, `test-e2e`, and `coverage` into one sourced script,
  and source it from those three recipes plus the new `pytest` recipe.
- Remove the `test` recipe. **BREAKING** for anything scripting `just test`. Document
  `uv run -- pytest -m unit` directly as the container-free unit-test command instead.
- Fix `podman *args:`'s unconditional `shift`, which silently drops the first argument whenever a
  contributor forgets the `--` separator (e.g. `just podman ps` would otherwise run bare `podman`
  instead of `podman ps`, with no error). Applied while introducing the identical, correctly-guarded
  pattern for the new `pytest` recipe.
- Update `CONTRIBUTING.md` to document `just pytest -- <args>` (including the `--` requirement,
  mirroring the existing `just podman -- <arguments>` convention) in place of "Use pytest directly
  for its selection options," and to document the direct unit command in place of `just test`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `development-environment`: the "Container-based contributors reach a container runtime without
  nesting" requirement gains coverage for the new generic `pytest` recipe as another documented
  container-backed test entry point that requires the same host Podman socket bridge.

## Impact

- `justfile`: new `pytest` recipe, removed `test` recipe, `test-integration`/`test-e2e`/`coverage`
  refactored to source the shared bridge script.
- New `scripts/testcontainers-bridge.sh`, sourced (not executed) by the four affected recipes.
- `CONTRIBUTING.md`: updated command-surface documentation.
- `openspec/specs/development-environment/spec.md`: delta for the requirement above.
