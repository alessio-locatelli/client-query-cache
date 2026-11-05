# Design

## Context

See `proposal.md` for motivation. Today `tox.ini` defines a `pymongo-min` environment that resolves the declared PyMongo floor with `lowest-direct`, installs the project wheel, and runs five behavioral test files. `just test-pymongo-min` wraps it, and the `pymongo-min` job in `test.yml` runs it after `uv sync --locked --no-default-groups --group compatibility`.

## Goals / Non-Goals

**Goals:**

- Reuse the job's synchronized environment and runner setup for every added release.
- Keep one source for the supported range (published metadata) and one for the test selection.

**Non-Goals:**

- Replacing the tox minimum lane, which also validates the `annotated-types` floor and an installed wheel.

## Decisions

### D1: Test every in-range release except the minimum and the locked one

The tox lane already runs the minimum and the full suite already runs the locked release in the same pull-request run, so repeating either is avoidable overhead.

| Alternative                                             | Pros                                                                   | Cons                                                                                               |
| ------------------------------------------------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Every in-range release (chosen, selected by the user)   | No list to maintain; catches regressions confined to one patch release | Run time grows with each release; a new release can fail an unrelated pull request; needs a lookup |
| Minimum plus newest patch per minor line                | Growth bounded by minor releases                                       | Misses a regression confined to a non-final patch; still needs the lookup                          |
| Minimum plus a hand-curated list tied to known concerns | Deterministic, cheapest, no lookup                                     | Starts empty so adds nothing today; depends on someone noticing a concern first                    |

Unknowns: the per-release duration and the resulting job time cannot be established without running it; the measurement task in `tasks.md` records both. Conclusion: no cap is added. The job's `timeout-minutes` fails the job visibly when the count outgrows it, and the response then is a selection-policy decision such as the per-minor row above. The declared minimum is a support-policy decision and is never raised to save CI time.

### D2: Swap PyMongo per release with `uv run --with "pymongo==<version>"`

A Just recipe loops over the selected releases and runs the shared selection once per release in the job's already-synchronized environment. Observed with uv 0.13.4 against this project:

- The overlay takes precedence over the locked PyMongo and reaches pytest-xdist workers, child processes, and spawn-started processes.
- uv does not enforce the project's declared specifier for `--with`: a pin below the floor installs silently, so range enforcement belongs to the release selection (D3).
- An unpinned `--with pymongo` is satisfied by the locked install, so every release is pinned with `==`. Pinning makes a separate version-equality assertion redundant.

Differences from the tox lane are accepted: the loop uses the editable project install rather than a built wheel, and it varies only PyMongo. Packaging is covered by other jobs.

| Alternative                              | Pros                                                                   | Cons                                                                                            |
| ---------------------------------------- | ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `uv run --with` loop (chosen)            | Reuses the synchronized environment and native build; no new framework | Editable install instead of wheel; per-release isolation is only the ephemeral overlay          |
| tox factor environments per release      | Existing tool; wheel-install parity with the minimum lane              | A fresh environment, wheel build, and test-dependency install per release                       |
| GitHub Actions matrix per release        | Parallel; isolated runners                                             | Repeats runner, Rust toolchain, and sync setup per release; the user ruled out per-release jobs |
| `uv pip install` loop in the shared venv | Low setup cost                                                         | Mutates the shared environment between releases                                                 |

Unknowns: none; the behaviors above were observed. Conclusion: no follow-up work.

### D3: Derive the release list with a small script fed by the package index

The recipe downloads PyPI's JSON release listing with `curl` and pipes it to a module under `scripts/` that prints the selected versions in ascending order, one per line. The module reads the specifier from the installed project's metadata (the source the tox minimum check already uses), takes the minimum from its `>=` bound, takes the locked release from the installed PyMongo, and treats a release as yanked when the index marks its files yanked (PyPI yanks whole releases). Splitting download from selection mirrors `scripts.ci_scope`, so selection is tested with fixture payloads and no network.

The module exits non-zero with a message on stderr for unusable input: invalid JSON, a missing `releases` key, a missing `pymongo` requirement, or a listing that lacks the declared minimum. The last case keeps an empty or truncated listing from passing as "no other release is in range", which stays a legitimate success. A failed download stops the recipe through the pipeline's failure status.

This departs from the user's original "no dedicated Python script"; the user accepted the script when choosing every release in D1. The module imports `packaging`, which the synchronized environment provides through pytest, as the tox minimum check already relies on.

| Alternative                                | Pros                                                                       | Cons                                                                                                    |
| ------------------------------------------ | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Script over the PyPI JSON listing (chosen) | Per-release yanked state in one request; PEP 440 filtering via `packaging` | PyPI-specific API; one more `scripts/` module                                                           |
| Script over the PEP 691/700 simple listing | Works with any compliant index                                             | Yanked state is per file, so filenames must be parsed back to versions; the lockfile uses only pypi.org |
| Shell with `curl` and `jq` alone           | No Python                                                                  | Cannot evaluate specifiers or pre-release rules                                                         |
| uv alone                                   | No script                                                                  | uv has no command that lists releases; a dry-run install reports only the highest match                 |

Unknowns: none requiring a prototype. A change to the JSON API surfaces as a visible failure. Conclusion: no follow-up work.

### D4: Share the test selection through a pytest argument file

A file under `tests/` lists the five behavioral test paths, one per line. The `pymongo-min` tox environment and the release recipe both run `pytest @<file>` and add their own log-file options. Pytest 9.2.0 accepts `@file` arguments, verified by collecting the selection from such a file.

| Alternative                                     | Pros                                                | Cons                                                                      |
| ----------------------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------- |
| Argument file (chosen)                          | Built into pytest; one list; no collection overhead | The tox and recipe commands refer to a file instead of inline paths       |
| Repeat the list in `tox.ini` and the `justfile` | No new file                                         | Silent drift between the two checks                                       |
| A pytest marker applied to the five modules     | Selection lives with the tests                      | Each release run would collect the whole `tests/` tree before deselecting |
| A Just variable exported to tox                 | One list                                            | Environment plumbing across three files; direct tox runs break without it |

Unknowns: none. Conclusion: no follow-up work.

### D5: Extend the existing `pymongo-min` job instead of adding a job

The recipe runs as a new step after `just test-pymongo-min`, so the runner, Rust toolchain, and `uv sync` are paid once and the stable `Python compatibility` gate needs no new input. The job's display name changes to cover both checks. Its id, the failure-artifact name, and the gate's environment variable stay unchanged: they are internal references, and the required check is the aggregate gate rather than any individual job. The failure-artifact paths gain the release logs.

A separate release job would repeat setup and add a gate input for no isolation benefit, because both checks need the same environment. Unknowns: whether the combined run fits the current 20-minute timeout, resolved by the measurement task. Conclusion: no follow-up work.

### D6: Stop at the first failing release

The recipe runs under `set -e`, so the first failing release stops the run (the fail-fast behavior the user requested). A second broken release is reported only after the first is fixed. Running every release and aggregating would report all failures at once but needs result bookkeeping and keeps running after the outcome is known; for a handful of patch releases a rerun is cheaper than the extra code.

Each release writes log files named after it, so a failure before pytest starts, such as during dependency installation, cannot leave an earlier release's log standing in for the failure. The recipe prints the release before each run, so the job log names the failing release.

### D7: Exclusions use published metadata

Excluding a defective release means adding a `!=` clause to the PyMongo requirement, which also steers adopters' resolvers and so needs a documented incompatibility under the existing "no documented incompatible release range" requirement. This change adds none: as of 2026-11-05 no in-range release is yanked or known to be defective. Yanked releases are filtered by the script because uv installs a yanked release when it is pinned with `==`.

### D8: Command overrides and where their rationale lives

The development-environment specification requires a rationale for each retained behavioral override at an allowed location. This section is that location for the new commands, so the recipe does not repeat it.

- `curl --fail`: The default exits 0 with the HTTP error body on a server error. We override it because an unusable index response must fail the recipe.
- `curl --silent --show-error`: The default prints a progress meter. We override it because logs should emphasize diagnostics while still showing errors.
- `curl --retry 3`: The default is no retry. We override it because a transient index error should not fail a pull request.
- `curl --max-time 60`: The default is no overall time limit. We override it because a stalled index request must not consume the job timeout.
- `pytest --log-file=pytest-pymongo-releases-<version>.log`: The default is `pytest.log`. We override it because release diagnostics must be distinct per release and from the locked-driver and minimum-driver logs.
- `pytest --log-file-level=WARNING`: The default is the `pytest.ini` DEBUG level. We override it because uploaded failure logs need bounded, actionable diagnostics.

## Risks / Trade-offs

- **Index unavailable or rate-limited** → The recipe fails visibly with `curl --retry` for transient errors; no cached fallback, because a stale list would silently test fewer releases. The job already needs the index for `uv sync`, so this adds no new class of dependency.
- **A new release turns an unrelated pull request red** → That is the intended early signal; maintainers fix the incompatibility or exclude the release through published metadata (D7). A rerun reflects the current release set.
- **Growth of run time** → Bounded by the job timeout and revisited per D1.
- **Repeated database startup** → Each pytest invocation starts its own disposable MongoDB container per xdist worker (at most four), so startup repeats for every release. Sharing one server across releases would need fixture support for an external server and would carry databases from one release into the next, so each release keeps its own run. The measurement task records the number and share of startups so that D1's policy can weigh them.
- **Editable install differs from the tox wheel** → Accepted in D2.
