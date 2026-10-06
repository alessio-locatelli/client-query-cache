# Configuration overrides

Most explanations live beside their configuration. This page covers strict JSON
and command options shared by several invocations. Follow the
[development-environment specification](../../openspec/specs/development-environment/spec.md)
when changing them; recheck the selected tool version and the invocation's inherited settings.

## npm quality commands

`package.json` selects Prettier 3.9.9 and markdownlint-cli2 0.23.3.
Sources: [Prettier CLI options](https://prettier.io/docs/cli) and
[markdownlint-cli2 options](https://github.com/DavidAnson/markdownlint-cli2/tree/v0.23.3#command-line).

- `private: true`: The default is false. We override it because this npm project
  supplies development tools and must not be published as a package.
- `scripts.format`'s `prettier --write`: The default is writing formatted content
  to standard output. We override it because this command repairs tracked files.
- `scripts.format:check`'s `prettier --check`: The default is formatting content
  to standard output. We override it because validation must fail on unformatted files.
- Both scripts' `prettier --cache`: The default is false. We override it because
  unchanged files should reuse formatting results during repeated quality runs.
- `scripts.format`'s `prettier --log-level warn`: The default is log. We override
  it because successful per-file formatting messages obscure actionable diagnostics.
- `scripts.format`'s `markdownlint-cli2 --fix`: The default is false. We override
  it because the formatting command should apply supported Markdown repairs.

## Taplo catalog failure

The `taplo-lint` hook intentionally replaces its inherited arguments; its rationale
is in `.pre-commit-config.yaml`. On 2026-10-06, the pinned ComPWA v0.9.3 hook
failed to decode `SchemaCatalog` with its inherited `--default-schema-catalogs`
argument. The same failure occurred with local Taplo 0.10.0:

```sh
taplo lint --default-schema-catalogs pyproject.toml
```

[Taplo issue 463](https://github.com/tamasfe/taplo/issues/463) records this catalog
decoding failure. The configured hook still checks TOML syntax; it does not load
the remote schema catalog.

## Command execution

These entries cover Just 1.57.0, uv 0.12.x (local 0.12.9, CI 0.12.19),
Git 2.55.0 locally, Bash 5.3 locally, and Python 3.14. Sources:
[Just settings](https://just.systems/man/en/settings.html),
[uv CLI](https://docs.astral.sh/uv/reference/cli/),
[uv environment](https://docs.astral.sh/uv/reference/environment/),
[Git config](https://git-scm.com/docs/git-config),
[Git worktree](https://git-scm.com/docs/git-worktree),
[Git revision output](https://git-scm.com/docs/git-rev-parse),
Bash's installed `bash --noprofile --norc -c 'help set'`,
[Python isolation](https://docs.python.org/3.14/using/cmdline.html#cmdoption-I), and
[Python subprocess](https://docs.python.org/3.14/library/subprocess.html).

- `justfile`'s `positional-arguments`: The default is false. We override it because
  `pytest` and `podman` recipes forward each original argument through `$@`.
- `justfile`'s `default-list`: The default is running the first recipe. We override
  it because invoking `just` without a recipe must list commands without running setup.
- `justfile`'s exported `UV_LOCKED=1`: The default is inherited from the caller's
  environment, otherwise unset. We override it because project recipes must reject
  a stale lockfile instead of resolving new dependencies.
- `justfile`'s `typecheck-examples` `env -u UV_LOCKED`: The default is the wrapper's
  exported value 1. We override it because isolated example environments resolve
  their own dependencies without the repository lockfile.
- `justfile`'s `verify-release` `unset UV_LOCKED`: The default is the wrapper's
  exported value 1. We override it because `--no-project` ignores that setting
  and warns about it; isolated artifact verification needs no project lockfile.
- Standalone `uv sync --locked` in `benchmarks/stream_cost/guard_runner.py`,
  standalone `uv run --locked` in the memory calibration example, and workflow
  syncs in `publish.yml`, `release-verification.yml`, `stream-cost-benchmark.yml`
  and `test.yml` jobs `prek`, `package`, `integration-e2e`, `memory`, `guard`,
  `benchmark-startup`: The default is inherited `UV_LOCKED`, otherwise unlocked
  resolution. We override it because these commands must validate the committed
  lockfile even when invoked outside Just.
- The workflow syncs above except `memory`, plus `guard_runner.py`, use
  `--all-groups`: The default is the project's default groups (dev). We override
  it because these validation environments need the documentation tools alongside
  development dependencies.
- `justfile`'s three documentation commands use `--only-group docs`: The default
  is the project and default groups (dev). We override it because documentation
  commands need only their declared tool environment.
- `justfile`'s `verify-release` uses `uv run --isolated --no-project`: The default
  is the discovered project environment. We override it because artifact import
  verification must use a fresh environment without the editable checkout.
- Its `python -I`: The default is normal environment/user-site/script-path
  loading. We override it because verification must import the installed artifact
  without incidental local packages.
- `justfile`'s Bash recipes `typecheck-examples`, `verify-release`, `pytest`,
  `enable-podman-socket`, `podman`, `test-memory`, `test-integration`, `test-e2e`,
  `tests_and_coverage` and `scripts/check_dev_container.sh` use `set -euo pipefail`:
  The default is inherited Bash startup/environment options, normally all three
  off. We override it because failed commands, unset variables and failed pipeline
  stages must stop these operations.
- `scripts/check_dev_container.sh`'s container `bash -e`: The default is off in
  this fresh Bash process. We override it because a failed version check must fail
  container validation.
- `scripts/build_versioned_docs.py`'s `git init -q` and `git commit -q`,
  `scripts/check_dev_container.sh`'s build `--quiet`, `justfile`'s setup/format
  npm `--silent` and typecheck-examples `uv sync --quiet`: The default is normal
  progress output. We override it because these contributor checks should emphasize
  diagnostics.
- `scripts/check_dev_container.sh`'s `run --rm` and the installation guide's
  `docker compose run --rm mongo_helper`: The default is retaining the stopped
  container. We override it because completed disposable checks/helpers should
  not leave stopped containers.
  Sources: [Docker run](https://docs.docker.com/engine/containers/run/) and
  [Compose run](https://docs.docker.com/reference/cli/docker/compose/run/).
- `scripts/build_versioned_docs.py`'s Git `--local`: The default is the inherited
  `GIT_CONFIG` file when set, otherwise repository-local writes. We override it
  because external-file redirection must be rejected before configuring the
  disposable artifact repository.
- Its `commit.gpgsign=false`: The default is inherited Git configuration for the
  disposable repository, including user/system scopes. We override it because
  artifact assembly must not request a developer's signing key.
- `guard_runner.py`'s `git worktree add --detach`: The default is attaching to a
  matching branch when the supplied name resolves to one, otherwise detaching at
  the commit. We override it because benchmark worktrees must remain detached
  even if a repository contains a branch whose name matches the resolved object ID.
- `decision_evidence.py`, `run.py`, and `compression_run.py` use
  `git rev-parse --short=7`: The default is the effective `core.abbrev` setting,
  otherwise Git's automatic abbreviation length. We override it because report
  identifiers need a consistent minimum seven-character abbreviation.
- `scripts/build_versioned_docs.py`'s `git` and `run` helpers and
  `guard_runner.py`'s `_run` helper use `subprocess.run(check=True)`: The default
  is false. We override it because failed external commands must abort assembly
  or benchmark preparation. Explicit `check=False` at ancestry/tool-probe calls
  is required by Ruff's `subprocess-run-check`; those callers inspect failure status.

`--file Containerfile` remains in `scripts/check_dev_container.sh`: Docker's
fallback filename is Dockerfile while the supported Podman builder also recognizes
Containerfile. It is a necessary build input across the supported engines.
Paths, image names, input filenames, versions, selected subcommands and predicates
are ordinary project inputs, not additional policy entries.

## Documentation and analysis tools

- `justfile`'s `docs-build` and `scripts/build_versioned_docs.py`'s root redirect
  build use `zensical build --clean`: The default is false. We override it because
  publication checks must rebuild without reusing the prior build cache.
- `justfile`'s `docs-build --strict` and `build_versioned_docs.py`'s edition and
  root-redirect `strict=True`: The default is false for the root configuration,
  or inherited from the extracted configuration for editions. We override it
  because all publication builds must fail on warnings, including broken links.
  Source: [Zensical 0.0.68 CLI](https://github.com/zensical/zensical/blob/v0.0.68/python/zensical/main.py)
  and its [configuration](https://github.com/zensical/zensical/blob/v0.0.68/python/zensical/config.py).
- `build_versioned_docs.py`'s two Mike commands use `--branch docs-artifact`:
  The default is inherited `remote_branch` configuration, otherwise gh-pages.
  We override it because assembly commits only to a disposable artifact branch.
- Both use `--ignore-remote-status`: The default is checking the remote branch.
  We override it because the disposable assembly repository has no remote.
  Source: [selected Mike revision 2d4ad799](https://github.com/squidfunk/mike/blob/2d4ad799442f4592db8ad53b179bfb33db8c69ac/mike/driver.py).
- `justfile`'s `lint` and `test.yml`'s `package` command use mypy
  `--install-types`: The default is false. We override it because these commands
  also install missing available stub packages.
- `justfile`'s `typecheck-examples` uses `--python-executable`: The default is the
  interpreter running mypy. We override it because each PEP 723 example has its
  own installed dependencies.
  Source: [mypy 2.3.1 command line](https://mypy.readthedocs.io/en/stable/command_line.html).
- `justfile`'s `ci-lint` uses `ZIZMOR_OFFLINE=true`: The default is false.
  We override it because local workflow inspection must not query GitHub APIs.
- That command's `--fix=all`: The default is no fixes. We override it because
  this repair command applies the auditor's available workflow corrections.
- Its `--persona=auditor`: The default is regular. We override it because local
  workflow review must include pedantic and lower-confidence findings.
- Its `-q`: The default is normal logging. We override it because diagnostics
  should remain visible without progress chatter.
  Source: [zizmor 1.30.0 usage](https://docs.zizmor.sh/usage/).
- `justfile`'s `lint` and `test.yml`'s `prettier` job use OpenSpec `--strict`:
  The default is false. We override it because specification warnings must fail
  the quality gate. `--all` selects project content.
  Source: OpenSpec 1.14.0 `openspec validate --help`.

## Pytest command overrides

These commands inherit `pytest.ini`; the configured defaults below differ from
pytest's built-ins. Sources: [pytest 9.1.1 options](https://docs.pytest.org/en/stable/reference/reference.html),
[xdist 3.8.0 distribution](https://pytest-xdist.readthedocs.io/en/stable/distribution.html),
[pytest-cov 7.1.0](https://pytest-cov.readthedocs.io/en/latest/config.html), and
[pytest-timeout 2.4.0](https://pypi.org/project/pytest-timeout/2.4.0/).

- `justfile`'s `test-integration`, `test-e2e`, `test-memory`, `tox.ini`'s four
  pytest environments and the memory calibration example use `-m`: The default
  is the configured `not memory` expression. We override it because each lane
  must select its designated integration, e2e, unit, benchmark or memory tests.
- `justfile`'s `test-memory`, `tox.ini`'s benchmark command, the memory calibration
  example, and the real-server benchmark commands in `CONTRIBUTING.md` and
  `docs/development/parallel-test-execution.md` use `-n 0`: The default is the
  configured auto worker count. We override it because allocation/latency
  measurements must run in one process without competing workers.
- The serial-debugging `-n 0` example in `parallel-test-execution.md`: The default
  is the configured auto worker count. We override it because serial execution
  helps isolate failures caused by distribution.
- `justfile`'s `test-integration`, `test-e2e`, `tests_and_coverage` supply
  `--log-file-level=WARNING` on GitHub Actions: The default is configured DEBUG.
  We override it because CI should retain warnings/failures without verbose
  successful-operation traces in uploaded logs.
- `justfile`'s `tests_and_coverage --cov`: The default is no coverage measurement.
  We override it because the correctness gate must enforce covdefaults' 100% threshold.
- Its `-qq`, `test.yml`'s benchmark-startup `-q`, and the `-q` examples in
  `concurrency-stress-tests.md` and `parallel-test-execution.md`: The default is
  verbosity zero. We override it because normal contributor/CI output should
  emphasize failures over successful test details.
- `test.yml`'s benchmark-startup `--timeout=120`: The default is configured 30s.
  We override it because disposable image startup can exceed the ordinary test budget.
- The stress example's `--timeout=300`: The default is configured 30s. We override
  it because its explicitly expanded stress workload needs a longer test budget.
- Memory tracing/capture/logging/timeout options share their explanation in
  [memory regression tests](memory-regression-tests.md#command-options).

## GitHub Actions

Platform behavior was checked against the [workflow syntax reference](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
(2026-10-06). Action inputs were checked at the revisions in the owning workflows:
[checkout v7.0.1](https://github.com/actions/checkout/blob/3d3c42e5aac5ba805825da76410c181273ba90b1/action.yml),
[setup-node v7.0.0](https://github.com/actions/setup-node/blob/820762786026740c76f36085b0efc47a31fe5020/action.yml),
[upload-artifact v7.0.1](https://github.com/actions/upload-artifact/blob/043fb46d1a93c77aae656e7c1c64a875d1fc6a0a/action.yml),
and [cache v6.1.0](https://github.com/actions/cache/blob/55cc8345863c7cc4c66a329aec7e433d2d1c52a9/action.yml).

- Workflow-level `permissions` in `dependency-automerge.yml`, `docs.yml`,
  `publish.yml`, `release-verification.yml`, `stream-cost-benchmark.yml`,
  `test.yml`: The default is inherited repository/organization token policy.
  We override it because workflow tokens need only read access until a specific
  publication job elevates its own grants. Dependency acceptance also reads live
  PR metadata; unspecified grants are none after declaring a permission map.
- `publish.yml`'s build-and-verify and publish-github-release `contents: write`:
  The default is the workflow's read grant. We override it because these jobs
  respectively create a draft release and publish the verified release.
- `publish.yml`'s publish `id-token: write`: The default is none under workflow
  permissions. We override it because PyPI Trusted Publishing requires OIDC.
- `docs.yml`'s deploy `pages: write` and `id-token: write`: The default is none
  under workflow permissions. We override it because Pages deployment requires
  both publication access and OIDC authentication.
- `cancel-in-progress: true` in `test.yml`, `release-verification.yml` and
  `dependency-automerge.yml`'s select job: The default is false. We override it
  because a newer validation/selection supersedes an unfinished older one.
- `docs.yml`'s `cancel-in-progress: true`: The default is false. We override it
  because the latest eligible controller must replace stale publication work.
  Its concurrency expression prevents ineligible runs from cancelling publication.
- All `timeout-minutes` entries: The default is 360. We override it because
  stalled jobs must stop within their assigned validation/publication budget.
  Covered jobs and values: dependency-automerge select/accept 5; docs build/deploy
  10; publish build-and-verify 15, publish/publish-github-release 10;
  release-verification release-verification 15; stream-cost-benchmark benchmark
  30; test scope/python-compatibility 5, prek/package 15,
  prettier/documentation/memory/benchmark-startup 10, integration-e2e/guard/container 20.
- `test.yml`'s package/integration-e2e `strategy.fail-fast: false`: The default
  is true. We override it because every supported Python lane must report its
  result even if another lane fails.
- Every checkout `persist-credentials: false`: The default is true. We override
  it because later repository commands must not inherit checkout credentials.
  Covered locations: docs build; publish build-and-verify; release-verification
  release-verification; stream-cost-benchmark benchmark; test scope, prek,
  prettier, documentation, package, integration-e2e, memory, guard, container,
  benchmark-startup.
- Checkout `fetch-depth: 0` in docs build and test scope/documentation/guard:
  The default is 1. We override it because source selection and revision
  comparisons require repository history beyond the checked-out commit.
- `docs.yml`'s checkout `ref: main`: The default is the event reference/SHA for
  this repository. We override it because the publication controller must use
  current trusted main rather than an earlier event snapshot.
- `test.yml`'s setup-node `cache: npm`: The default is automatic npm caching only
  when supported package-manager metadata selects npm; this package.json supplies
  no such metadata. We override it because CI should reuse locked npm downloads.
- `test.yml`'s cache `restore-keys` for prek-results, prettier, mypy and
  pytest-hypothesis: The default is no prefix fallback. We override it because
  these keys preserve their compatible environment/dependency inputs while
  allowing reuse across commits.
- Upload `retention-days` in publish build-and-verify (7), stream-cost-benchmark
  benchmark (30), test integration-e2e/memory (7) and guard (30): The default is
  inherited repository/organization artifact retention. We override it because
  intermediate release artifacts and diagnostics need bounded storage lifetimes.
- Test integration-e2e/memory uploads' `if-no-files-found: ignore`: The default
  is warn. We override it because failures before test execution can legitimately
  produce no diagnostic file.
- `test.yml`'s guard upload and `stream-cost-benchmark.yml`'s upload use `always()`:
  The default is implicit success(). We override it because partial reports must
  remain available after failed measurement commands.
- `test.yml`'s python-compatibility job uses `always()`: The default is implicit
  success(). We override it because failed matrix prerequisites must cause the
  aggregate gate to fail visibly instead of skipping it.
- Test integration-e2e/memory uploads use `failure()`: The default is implicit
  success(). We override it because these diagnostics are needed on failed runs.
- `test.yml`'s guard command uses `set -o pipefail`: The default is off in the
  platform's unspecified Linux shell (`bash -e`). We override it because a failed
  benchmark must fail the step even when tee successfully writes its summary.

Privileged safety pins and token scopes have their explanations directly in
`publish.yml` and `dependency-automerge.yml`. Paths, event selectors, matrices,
cache keys, action identifiers and selected environments remain project inputs.

Additional command policies:

- `justfile`'s `enable-podman-socket` uses `systemctl --user` twice: The default
  is the system manager. We override it because the socket belongs to the host
  user's rootless Podman service.
- Its `systemctl enable --now`: The default is enabling without starting the
  service. We override it because the following readiness checks require a live socket.
- Its `systemctl is-active --quiet`: The default is printing unit state. We
  override it because the command's exit status controls the visible failure message.
  Source: [systemctl options](https://www.freedesktop.org/software/systemd/man/latest/systemctl.html).
- `justfile`'s enable-podman-socket and podman recipes use `flatpak-spawn --host`:
  The default is spawning through the sandbox portal. We override it because
  Toolbx must reach the host's user service and container engine.
  Source: [flatpak-spawn](https://docs.flatpak.org/en/latest/flatpak-command-reference.html#flatpak-spawn).
- `test.yml`'s Prek `SKIP=slotscheck,prettier,lychee`: The default is no skipped
  hooks. We override it because slotscheck and formatting run in their dedicated
  lanes, while Lychee runs separately with its step-scoped GitHub token.
  Source: [Prek hook skipping](https://prek.j178.dev/quickstart/#temporarily-disabling-hooks).
- The two fetch commands in each of docs.yml/test.yml's documentation jobs and
  the correction-ref example in CONTRIBUTING.md use `git fetch --no-tags`:
  The default is inherited remote.origin.tagOpt, otherwise automatically
  following reachable tags. We override it because assembly needs only its
  explicitly selected release/correction references.
  Source: [Git fetch](https://git-scm.com/docs/git-fetch).
- `dependency-automerge.yml`'s select and accept steps use jq `-e` (including
  `-er`) for actor, unique-candidate and live-PR checks: The default is a zero
  exit status after successful evaluation, including false/null results. We
  override it because rejected metadata and empty selections must take the
  rejection branch before credential issuance or acceptance.
  Source: [jq exit status](https://jqlang.org/manual/#invoking-jq).
- Its approval call's `gh api --silent`: The default is printing the response.
  We override it because successful approval metadata should not obscure diagnostics.
- Its `gh pr merge --auto`: The default is requesting immediate merging. We
  override it because native auto-merge must wait for required checks and repository rules.
- Its `--rebase`: The default is an unset merge method resolved through repository
  capabilities and CLI selection. We override it because accepted dependencies
  use the repository's rebase merge policy.
- Its `--match-head-commit`: The default is no supplied head constraint. We
  override it because acceptance must not merge a newer unvalidated PR head.
- `publish.yml`'s `gh release create --draft`: The default is publishing the
  release. We override it because the GitHub release stays staged until PyPI succeeds.
- Its `gh release edit --draft=false`: The default is preserving the release's
  existing draft state. We override it because successful PyPI publication must
  expose the staged GitHub release.
- CONTRIBUTING.md's `gh api --method POST` force-cancel example: The default is
  GET without request fields. We override it because force-cancellation requires
  the endpoint's POST operation.
- `executable-version-updates.md`'s local Renovate `--platform=local`:
  The default is GitHub. We override it because audit commands must inspect the
  checkout without updating hosted pull requests.
- Its `--dry-run=extract` and `--dry-run=lookup`: The default is no dry run.
  We override it because local policy inspection must stop before any updates.
- Both commands' `LOG_LEVEL=debug`: The default is info. We override it because
  policy inspection needs resolved extraction/lookup details.
  Source: [Renovate 44.133.0 self-hosted options](https://docs.renovatebot.com/self-hosted-configuration/).

GitHub CLI command behavior uses local 2.97.0 and the documented hosted interface:
[API](https://cli.github.com/manual/gh_api),
[merging](https://cli.github.com/manual/gh_pr_merge),
[release creation](https://cli.github.com/manual/gh_release_create), and
[release editing](https://cli.github.com/manual/gh_release_edit).
Quiet npm options use [npm loglevel](https://docs.npmjs.com/cli/v11/using-npm/config#loglevel).

## Disposable MongoDB

Sources: [Docker resource limits](https://docs.docker.com/engine/containers/resource_constraints/)
and [PyMongo 4.18 client options](https://pymongo.readthedocs.io/en/4.18.1/api/pymongo/mongo_client.html).

- `benchmarks/stream_cost/topology.py`'s `with_kwargs(nano_cpus=..., mem_limit=...)`:
  The default is no explicit per-container CPU/memory limit. We override it
  because each benchmark must run under its declared resource budget.
- `tests/conftest.py` and `topology.py` supply `directConnection=true` in their
  URIs: The default is false. We override it because discovery would follow the
  internally advertised localhost address instead of the mapped container port.
- Both startup clients use `serverSelectionTimeoutMS=1000`: The default is
  30000 ms. We override it because bounded polling needs short connection attempts
  before its own startup deadline.
- Their `with_command` calls supply `--replSet`: The default is no replica set.
  We override it because the disposable runtime must support change streams.
  Source: [MongoDB 8.0 mongod options](https://www.mongodb.com/docs/v8.0/reference/program/mongod/).

## Contributor examples

- `parallel-test-execution.md`'s `-n 2`, `-n 8`, and serial `-n 0 tests/core`
  examples: The default is the configured automatic worker count. We override
  it because these examples select a concrete worker budget for available resources.
- Its `PYTEST_ADDOPTS='-n 0'` coverage comparison: The default is no additional
  environment-supplied options. We override it because that comparison must
  disable the configured automatic workers while keeping the coverage recipe.
  Source: [pytest addopts precedence](https://docs.pytest.org/en/stable/how-to/usage.html#specifying-which-tests-to-run).
- Its two `CI=true` coverage comparison commands: The default is inherited from
  the caller's environment, otherwise unset. We override it because comparison
  must use the external-server benchmark's documented CI skip policy.
- Its debugging `-s`: The default is configured fd capture. We override it because
  interactive debugging needs live standard input/output.
- Its `--pdb`: The default is false. We override it because the example opens the
  debugger at the failure site.
- `executable-version-updates.md`'s `gh pr merge --disable-auto`: The default is
  requesting a merge. We override it because rollback must cancel an existing
  native auto-merge request.
- Its dispatch `--ref main`: The default is the repository's default branch.
  We override it because acceptance must execute the trusted main controller,
  independently of the repository's configured default branch.

The main/eligibility predicates in `docs.yml` build and
`dependency-automerge.yml` select/accept, and its metadata/configuration/app-token/
acceptance steps: The default is the platform's implicit success() condition
without these additional eligibility restrictions. We override it because
publication and acceptance must use trusted main and verified live metadata
before acquiring or using privileged credentials.
