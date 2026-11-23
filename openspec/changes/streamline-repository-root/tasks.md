# Tasks

## 1. Local checkout and configuration

- [x] 1.1 Recheck local root entries by pathname and apply the local moves in D4 and the migration plan before commands generate replacement output. Verify preserved files are reachable at the new or original path and record any collisions.
- [x] 1.2 Apply D1. Update stale configuration references in the existing tool probes, CI path selector, pytest cache key, recipes, and contributor docs. Compare effective tox settings with `tox config -e` for each existing lane, compare coverage settings with `coverage debug config`, and compare pytest collection and Ruff discovery against the original checkout. Run the updated type-checker probes and exercise the spelling hook.

## 2. Standalone configuration

- [x] 2.1 Apply D2 for Gitlint, Detect Secrets, Taplo, Vulture, Lychee, and ast-grep. Exercise the installed commit hook with a known invalid message using a disposable checkout, verify each hook selects the moved input, and confirm both Taplo hooks retain submodule exclusions. Run the ast-grep rule tests and check that `scan` still reports a known rule violation in a scratch fixture.
- [x] 2.2 Apply the Renovate, container, and Compose moves in D2. Update the path allowlist in `.github/workflows/dependency-automerge.yml`, its existing tests, the CI scope tests, and the executable-version guidance. Verify the existing container check builds the moved definition, the dependency managers still select their pinned inputs, and the documented Compose command renders the same service configuration for the checkout.
- [x] 2.3 Apply the Prettier and Markdownlint moves in D2. Verify both npm formatting commands honor the rebased exclusions and still process repository-owned files with similar names. Exercise the updated formatting selector with a change to the moved ignore file.

## 3. Generated output

- [x] 3.1 Apply D4 for pytest logs. Update the logging and benchmark instructions, all lane upload globs in `.github/workflows/test.yml`, and the existing chart command. In a fresh checkout, exercise a serial test and two workers, then check a custom log path and the null device. Verify lane-specific controller and worker names match the failure-upload globs.
- [x] 3.2 Apply the Zensical move in D2 and the site output change in D4. Update the contributor guide, existing edition-build fixtures, and site path selector test. Check `just docs-build` and extend the existing edition-build cases to cover a mixed-layout build and recovery after a failed replacement. Verify the Pages artifact contains both editions, the root redirect, and the verification file.
- [x] 3.3 Apply the remaining configured output moves in D4 and update the current benchmark, memory, and CI cache guidance. Verify `just setup-rust` and the static Rust checks locate the installed tools. Use the smallest existing representative report runs to verify the producer and uploader agree on the artifact paths.

## 4. Root inventory

- [x] 4.1 Compare the final root with D1–D4 using `git ls-tree` and a path-only listing of local entries. Verify configured workflows leave no new root output and all retained root or legacy paths have an inventory disposition.
