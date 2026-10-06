# Contributing

Develop inside the Toolbx or Distrobox image, or an equivalent environment with the declared
tools on `PATH`.

## Prerequisites

- [Rootless Podman](https://podman.io/docs/installation) and a systemd user session
- [Toolbx](https://containertoolbx.org/install/) with `flatpak-spawn` and a working Flatpak
  portal/session helper, or [Distrobox](https://distrobox.it/#installation)

## Environment

The image pins its base digest, Python, and tools installed outside DNF. DNF selects
`bash`, `just`, `nodejs24`, `nodejs24-npm`, and `uv` from the Fedora 44 repositories
at build time; Node.js stays on the 24 package track. These package versions are
unpinned because the selected update bots cannot safely update the Fedora RPM pins:
Renovate’s [RPM parser](https://github.com/renovatebot/renovate/blob/main/lib/modules/datasource/rpm/providers/xml.ts)
omits epochs and architecture filtering.

We accept the loss of identical RPM versions across rebuilds. Fedora updates to
these development tools are expected to have a low risk of breaking the environment.
They are not dependencies of the published library, whose Python dependencies
remain declared separately. Tool updates can still affect installation, validation,
or benchmark results, so validate the rebuilt image before using it.

From the host, build the image and create a Toolbx container:

```console
podman build --tag localhost/client-query-cache-dev:0.1.0 --file Containerfile .
podman container exists client-query-cache-dev || toolbox create --image localhost/client-query-cache-dev:0.1.0 client-query-cache-dev
```

For Distrobox, use:

```console
podman container exists client-query-cache-dev || distrobox create --image localhost/client-query-cache-dev:0.1.0 --name client-query-cache-dev
```

Inside the container, open the checkout and run:

```console
just setup
```

## Executable updates

See the [executable update inventory and validation commands](docs/development/executable-version-updates.md).
CI and the development image use the exact Python patch selected in `.python-version`.

## Validate changes

Inside Toolbx or Distrobox, enable the host Podman socket before the full test suite:

```console
just enable-podman-socket
just tests_and_coverage
```

`just tests_and_coverage` runs the current test suite and reports coverage. Run `just pytest -- -m unit` for
the container-free unit-test tier. To discover focused recipes, run:

```console
just --list | grep -E 'test|coverage'
```

For a specific path, node ID, or other pytest argument, run `just pytest -- <arguments>` — always
include the leading `--`, mirroring `just podman -- <arguments>` below, since some pytest flags
(such as `-q` or `-v`) share a letter with `just`'s own short flags. Run `just lint` and
`just format` for repository quality checks, and run `just ci-lint` after changing GitHub Actions.

Run `just examples` to run every program in [`examples/`](examples/README.md) against a disposable replica set. The first run downloads each example's libraries.

See the [CI validation cache inventory](docs/development/ci-validation-caches.md) for the tools run on GitHub Actions and their cache paths.

See [parallel test execution](docs/development/parallel-test-execution.md) for worker defaults,
explicit worker counts, serial troubleshooting, coverage, and log locations.

Run host Podman commands from the contributor container with `just podman -- <arguments>`.

Run `just test-memory` for the opt-in memory regression tier on Linux; it requires no MongoDB.
See the [workload, allocation limits, and calibration guide](docs/development/memory-regression-tests.md).

The integration suite includes [mixed concurrency stress tests](docs/development/concurrency-stress-tests.md).
That guide documents cycle counts and longer local runs.

## Documentation

Edit published guides and assets in `docs/user/`. Repository-only architecture, maintainer notes, decisions, and research live in `docs/development/`; use its [development index](docs/development/index.md) to find them. Only `docs/user/` is published.

[`context7.json`](context7.json) selects public guides and summarizes usage rules for Context7. It excludes `docs/user/examples/`, whose snippet wrappers require the site build to expand canonical programs and catalogue content. Complete integration examples remain available on the hosted documentation site. Keep its rules aligned with the implementation and canonical guides in `docs/user/`. Update affected rules and guides in the same change as code, including return contracts, eligibility, consistency, lifecycle, and deployment requirements. Review each rule's meaning against the code and guides; JSON validity alone does not establish alignment. See [Context7's library-owner documentation](https://context7.com/docs/library-owners) for configuration fields.

Keep one canonical source for each detailed topic. The example command/prerequisite catalogue stays in `examples/README.md`, and runnable programs stay in `examples/*.py`. Hosted example pages include these files with `pymdownx.snippets`, using repository-relative paths and `check_paths = true`. Include program text in Python code blocks; surround snippet-only fences with `<!-- fmt:off -->` and `<!-- fmt:on -->` so [Ruff Markdown formatting](https://docs.astral.sh/ruff/formatter/#markdown-code-formatting) preserves the inclusion directive. Never import or execute examples during a site build. Link the canonical file from each wrapper for repository readers.

Link hosted guidance with relative Markdown paths and heading fragments. Use clearly labelled, explicit GitHub links for source files, checkout instructions, development documentation, and benchmark evidence. Keep revision-pinned evidence links pinned. Do not use GitHub READMEs as substitutes for hosted tutorials or examples. After moving a public page or heading, update local links and Zensical's page/anchor redirect mappings so existing bookmarks still reach hosted guidance.

```console
just docs-serve
just docs-build
```

These commands preview the working tree. The hosted site instead defaults to the latest published release, with a `Development (main)` selector.

The preview prints its local URL and reloads when guides change. The build creates untracked output in `site/`, fails on missing local pages, headings, or snippets, and uses the locked `docs` dependency group. These commands need no MongoDB, Docker, or hosting credentials. The existing Lychee Prek hook checks authored links and assets. See [Zensical's documentation](https://zensical.org/docs/) for authoring and framework configuration.

After `just docs-build`, inspect `site/llms.txt` for the public section index and `site/llms-full.txt` for the combined rendered guidance. Follow the index's URLs to locate page Markdown: directory URLs export `reference/api.md` as `site/reference/api/index.md`, while Home exports as `site/index.md`. Snippets are expanded in these files and in the HTML page's **Copy as Markdown** action. All exports stay untracked alongside HTML in `site/`. See [Zensical's native `llmstxt` documentation](https://zensical.org/docs/compatibility/mkdocs/plugins/#llmstxt) for export settings.

Lychee cannot confirm new hosted routes before publication. Its accepted limitation excludes remote checks for the public section prefixes and the two unpublished edition prefixes; local links still undergo link checking and strict site validation. Inspect README's direct hosted links and the example catalogue's hosted links in the local preview, then inspect the deployed revision after publication. See the [documentation validation limitations](docs/development/ci-validation-caches.md#documentation-validation-limitations).

### Inspect both editions

```console
just docs-build-editions v0.2.0
python -m http.server --directory site
```

The combined build uses exact local Git refs and writes one untracked artifact to `site/`. Open `/` to follow the stable default; the selector offers exactly `Latest release (X.Y.Z)` and `Development (main)`. Local serving uses the site root, so existing direct page links and edition switching also work. No hosting credentials, MongoDB or example execution are required. Ordinary preview commands remain useful for uncommitted prose; combined builds use committed snapshots. Rendering uses standard temporary storage, including `TMPDIR` overrides, without requiring write access to the checkout parent. Complete output is staged beside `site/` before replacement. Installation failure restores the previous artifact; if restoration also fails, the error identifies a recoverable `.docs-previous-*` sibling outside temporary-directory cleanup. Preserve that directory until you have recovered its contents.

After `just docs-build-editions`, root `site/llms.txt` is a byte-for-byte copy of stable guidance; its page links point into `/stable/`. Enabled combined output is copied to the root using the stable policy’s filename, normally `site/llms-full.txt`. Inspect `site/stable/llms.txt` and `site/dev/llms.txt`, each edition’s configured combined output, and their linked page Markdown to check the independent corpora. For example, API exports live at `site/stable/reference/api/index.md` and `site/dev/reference/api/index.md`. Each edition uses its own native export settings and offers **Copy as Markdown**. Stable sources that lack export settings inherit the selected development snapshot's settings; root exports follow the effective stable policy, including its combined-output filename or disabled state.

`stable-docs.toml` records the explicit PR validation tag and a bounded documentation correction source for `v0.2.0`, whose released guides predate this layout. The source is a reviewed immutable commit, not a moving branch. The `fetch_ref` field gives both workflows a supported retrieval ref: a dedicated documentation tag or GitHub’s retained `refs/pull/ID/head`. They fetch that named ref into the local repository; the builder verifies it reaches the pinned source SHA and never substitutes its current tip. GitHub preserves this [PR ref after closure](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/checking-out-pull-requests-locally?platform=mac), including after rebase merge and source-branch deletion. A force-rebase before merge can remove the pinned commit from that ref; update and review the record in that case, or use an already published dedicated tag. Missing or unreachable sources fail visibly. Before accepting it, the builder compares the release's package source tree, executable example files and runtime `[project]` metadata. Any mismatch fails visibly. It records release, stable docs and development commits in build output and rewrites stable checkout/source links to that docs commit, leaving pinned benchmark evidence intact.

A future release containing the guide layout builds directly from its tag without an override. To correct released prose, review and commit a documentation-only snapshot with matching runtime inputs, then replace the exact tag's immutable record. Keep a single bootstrap record rather than duplicating a guide tree. Update `validation_tag` when moving the PR validation baseline to a newer release. Fetch the release tag and recorded correction ref locally before building, for example `git fetch --no-tags origin refs/pull/143/head:refs/pull/143/head`; PR CI fetches it explicitly without discovering mutable release identity. The maintained [mike integration](https://zensical.org/docs/compatibility/mkdocs/mike/) owns version metadata and selection; Zensical renders both editions and root redirects.

Pull requests affecting site inputs run **Documentation build** after **Prek** and **Prettier, Markdownlint, and OpenSpec**. If configuring required checks, require all three independently: GitHub can report a dependent job skipped after a failed prerequisite as successful. Guide-only Markdown changes do not select Python or database tests.

### Publishing

An administrator must select **GitHub Actions** as the Pages publishing source and restrict the `github-pages` environment's deployment branches to `main`. Review any environment approval requirements before rollout. See GitHub's [Pages workflow setup](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) and [environment protection guidance](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments). Public repositories can use the free project URL, `https://alessio-locatelli.github.io/client-query-cache/`, without a custom domain.

**Publish documentation** runs after relevant `main` changes, main-only manual dispatch, or successful completion of **Publish to PyPI**. Failed/cancelled publication runs cannot deploy. It always checks out trusted `main` controller code and resolves GitHub’s current latest published non-draft, non-prerelease release. A delayed older release completion therefore builds the current stable edition. It never consumes code or artifacts from the triggering run. Both committed source snapshots and root redirects must build before one complete artifact is uploaded; a newer eligible run requests cancellation of the queued or running one instead of waiting behind it, and the site keeps its previous content until the newer deployment succeeds. Runs that are ineligible to publish never cancel or replace an eligible run. It uses GitHub's token and OIDC; no personal token is needed. Build and hosting configuration failures remain visible workflow failures. To redeploy, [run the workflow manually](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow) with `main` selected; other branches cannot publish. GitHub decides when a cancelled run is released; if a run stays queued after cancellation, an administrator can [force-cancel it](https://docs.github.com/en/rest/actions/workflow-runs#force-cancel-a-workflow-run) with `gh api --method POST repos/alessio-locatelli/client-query-cache/actions/runs/<run-id>/force-cancel`.

To roll back, revert the faulty controller/configuration or documentation correction record on `main` and redeploy a complete working artifact. Preserve published package tags and stable-source provenance; do not substitute development guides for released behavior. If no working site exists, an administrator can disable the workflow and Pages hosting. Repository Markdown remains available.

## Changelog

Every user-facing change adds a one-line entry under `CHANGELOG.md`'s "Unreleased" section describing the final behavior, not the review history that led to it.

## Real-server benchmark

`just tests_and_coverage` and `just pytest` include a benchmark that measures the cache's benefit
against a real, externally hosted MongoDB deployment — for example, a free-tier
[MongoDB Atlas](https://www.mongodb.com/cloud/atlas/register) cluster. It reads a connection string
from `REAL_MONGODB_URI` in a `.env` file at the repository root (see `.env.example`), which `uv`
loads automatically once that file exists. Without a configured `.env`, or in CI, the benchmark
skips with an explicit reason and every other test still runs.

Run just this benchmark with:

```console
just pytest -- -n 0 tests/benchmark/real_server/test_cache_benefit.py
```

Its logged evidence, including any Atlas bandwidth evidence described below, lands in `pytest.log`
at the repository root; search that file for the test's name instead of scrolling the full suite's
output.

Run it serially for isolated measurements. In an ordinary parallel full-suite run it competes
with other test workers, and its evidence lands in that worker's `pytest-gw*.log` file.

If `.env` also sets `REAL_MONGODB_ATLAS_PROJECT_ID` to your MongoDB Atlas project's ID, and the
[Atlas CLI](https://www.mongodb.com/docs/atlas/cli/current/) is installed and authenticated, the
benchmark additionally collects that project's network-bandwidth metrics covering its combined
cached-and-uncached read phases and logs them for your own inspection. This evidence never gates the
benchmark's pass/fail result: without `REAL_MONGODB_ATLAS_PROJECT_ID`, without the Atlas CLI, or if a
metrics call fails, the benchmark logs the gap and continues running as usual.

A small shared-tier deployment's metrics only refresh every few minutes, on an irregular interval,
and the freshest couple of minutes never have a sample yet by the time the benchmark asks — so this
evidence frequently reads as all zero, and even a non-zero reading is dominated by the deployment's
ambient baseline traffic rather than this specific run's few seconds of reads and writes. A zero or
unchanged reading here does not mean the cache did something wrong; it means this tier's metrics are
too coarse to isolate a single local benchmark run. Look for a real bandwidth anomaly on a longer
timescale in the Atlas UI instead of from a single run's logged evidence.

## Release verification

`just verify-release` builds the source and wheel distributions, installs each into its own isolated environment, and imports the public synchronous and asyncio API from each installation — the same check the "Static checks, packaging, and isolated install" CI job runs on every pull request that changes Python files, `pytest.ini`, `pyproject.toml`, or `uv.lock`. It publishes nothing and needs no credentials.

Pass a candidate release tag to also check it against the version declared in `pyproject.toml`:

```console
just verify-release v1.2.3
```

A mismatch fails with an actionable error; a match succeeds without creating a tag or any other release state.

The same check is also available as the manual "Release verification" GitHub Actions workflow (`workflow_dispatch`, with an optional `tag` input) for verifying a candidate release from the GitHub UI or `gh workflow run` without a local checkout.

## Releasing

Before the first release, complete the [one-time PyPI publishing setup](docs/development/pypi-publishing-setup.md).

### Per-release steps

1. Bump the `version` field in `pyproject.toml`'s `[project]` table to the new `X.Y.Z`.
2. In `CHANGELOG.md`, rename "Unreleased" to `[X.Y.Z] - YYYY-MM-DD` and open a new empty
   "Unreleased" section above it.
3. Commit these changes.
4. Tag the commit: `git tag vX.Y.Z`.
5. Push the tag: `git push origin vX.Y.Z`.

Pushing the tag triggers the `publish.yml` workflow, which builds and verifies the release
artifacts, then pauses for the `pypi` environment's required reviewer to approve before uploading to
PyPI and creating the matching GitHub Release.
