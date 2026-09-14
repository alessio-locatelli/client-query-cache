## Context

See proposal.md - Why. `test-integration`, `test-e2e`, and `coverage` each carry an identical
`#!/usr/bin/env bash` block that detects Toolbx vs. Distrobox vs. `GITHUB_ACTIONS`, exports
`DOCKER_HOST`/`TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE`/`TESTCONTAINERS_RYUK_PRIVILEGED`, or exits 1
with an actionable message. `openspec/changes/archive/2026-09-06-add-just-workflow/design.md` and
`.../2026-09-12-streamline-contributor-workflow/design.md` already established why this lives
inline in each recipe rather than as a dependency: `just` runs every recipe invocation, and every
recipe-to-recipe dependency, as an independent subshell, so a variable exported by one recipe is
never visible to another. That constraint blocked deduplication at the time; it does not block
deduplication through a plain sourced shell script, since `source` runs within the _same_ subshell
that later invokes `pytest`.

`just`'s own CLI has single-letter flags (`-q`, `-v`, `-l`, `-s`, `-n`, `-f`, `-d`, `-e`, `-c`,
`-g`, ...) that share a letter with common pytest flags. Empirically, the pinned `just` version does
not actually intercept these once it has resolved the recipe name - see the rejected alternative
under Decisions - but the existing `podman *args:` recipe already established the project's answer
regardless: document the call as `just podman -- <arguments>` and `shift` the leading `--` out of
`"$@"` inside the recipe body, as a convention rather than a currently-required workaround.

## Goals / Non-Goals

**Goals:** Let a contributor or agent run `pytest` with arbitrary arguments through `just` without
manually reproducing the container-runtime bridge; remove the duplicated bridge block from three
recipes down to one sourced implementation; remove the `test` recipe, which added no behavior over
its own body.

**Non-Goals:** Change what `test-integration`, `test-e2e`, or `coverage` select or how they report
results; change the Toolbx/Distrobox detection or socket-path logic itself; add pytest-argument
validation or a curated flag allow-list (the recipe is a pure pass-through).

## Decisions

- **Extract the bridge block into `scripts/testcontainers-bridge.sh`, sourced (not executed) by
  each recipe.** The script no-ops under `GITHUB_ACTIONS=true` (CI's native Docker needs no
  override) and otherwise detects Distrobox/Toolbx, exports the three variables, or prints the
  existing actionable message and `exit 1`. Because it is sourced into the calling recipe's own
  `bash` subshell rather than executed as a separate process, its exports remain visible to the
  `pytest`/`coverage` invocation that follows in the same recipe body - this is the piece the
  earlier duplication was accepted around, and a sourced script (as opposed to a `just` dependency
  recipe) is the one form that avoids the subshell boundary and still reproduces the guard exactly.
  Referenced via `{{justfile_directory()}}/scripts/testcontainers-bridge.sh` so it resolves
  correctly regardless of the caller's working directory.
- **`pytest_log_args` (the CI-only `--log-file-level=WARNING` flag) stays inline in each of
  `test-integration`/`test-e2e`/`coverage` rather than moving into the shared script.** It is a
  one-line, recipe-specific logging concern unrelated to the container bridge, and the new `pytest`
  recipe has no fixed log-file destination to default for arbitrary ad hoc invocations.
- **New `pytest *args:` recipe is documented as `just pytest -- <args>`, matching `podman *args:`'s
  convention, but shifts conditionally rather than unconditionally:** `[[ "${1:-}" == "--" ]] &&
shift` before `exec uv run -- pytest "$@"`. `podman`'s existing unconditional `shift` silently
  drops whatever the first argument happens to be, `--` or not; a contributor who forgets `--`
  before a plain node ID (e.g. `just pytest tests/foo.py::test_bar`, which no `just` flag collides
  with) would otherwise have that argument silently discarded and the full suite would run instead
  of the targeted test, with no error. Checking for a literal `--` instead makes forgetting it
  harmless (the argument list passes through unshifted) rather than silently wrong, and a bare
  `just pytest` with zero arguments (a plausible way to run the whole suite through this recipe)
  never reaches the `shift` at all.
  - Alternative considered: skip the `--` convention entirely and rely on `just` not intercepting
    flags after the recipe name (verified empirically against the pinned `just` version). Rejected
    because it silently breaks the moment `just` changes that parsing behavior, is inconsistent with
    the already-documented `podman` convention, and gives users no visual cue for which flags belong
    to `just` versus `pytest`.
- **`pytest` always sources the bridge script, matching `test-integration`/`test-e2e`/`coverage`.**
  `just` itself is only ever installed inside the Toolbx/Distrobox image (the host bootstrap
  explicitly does not require `just`), so there is no bare-host scenario where the Toolbx/Distrobox
  guard would incorrectly block a legitimate unit-only invocation.
- **Apply the same `[[ "${1:-}" == "--" ]] && shift` fix to the pre-existing `podman *args:`
  recipe.** It has the identical unconditional-`shift` defect: `just podman ps` (a real contributor
  command, forgotten `--`) silently drops `ps` and runs bare `podman` instead, with no error.
  Confirmed still exercised in practice - it satisfies the `development-environment` spec's
  interactive-Podman-alias scenarios - so it is fixed here rather than removed, using the exact fix
  validated for `pytest` above.
- **Remove `test` outright rather than keeping it as an alias.** `uv run -- pytest -m unit` is the
  entire recipe body; keeping a one-line wrapper whose name does not communicate its unit-only
  scope adds an indirection with no behavior to justify it. `CONTRIBUTING.md` documents the direct
  command in its place.

## Risks / Trade-offs

- [Removing `test` breaks a script or muscle-memory that invokes `just test`] → It is not referenced
  by any CI workflow (only `just coverage` is); `CONTRIBUTING.md` documents the literal replacement
  command in the same place `test` was documented.
- [A future contributor reintroduces bridge-detection duplication by adding a fifth pytest-invoking
  recipe inline] → The sourced script is now the one place that logic lives; review should point new
  container-backed recipes at it.
- [A future `just` release starts intercepting recipe arguments like `-q`/`-v` after the recipe
  name, unlike the pinned version tested here] → The `--` convention is documented in
  `CONTRIBUTING.md` next to the existing `podman -- <arguments>` example, so contributors who follow
  it are unaffected regardless of that change.

## Migration Plan

Add `scripts/testcontainers-bridge.sh`, refactor the three existing recipes to source it, add the
`pytest` recipe, remove `test`, and update `CONTRIBUTING.md` in the same change. No data migration
or rollout sequencing is needed; reverting is a plain revert of the justfile/script/doc changes.
