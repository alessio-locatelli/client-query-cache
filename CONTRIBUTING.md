# Contributing

Develop inside the pinned Toolbx or Distrobox image, or an equivalent environment with the declared
tools on `PATH`.

## Prerequisites

- [Rootless Podman](https://podman.io/docs/installation) and a systemd user session
- [Toolbx](https://containertoolbx.org/install/) with `flatpak-spawn` and a working Flatpak
  portal/session helper, or [Distrobox](https://distrobox.it/#installation)

## Environment

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

## Validate changes

Inside Toolbx or Distrobox, enable the host Podman socket before the full test suite:

```console
just enable-podman-socket
just tests_and_coverage
```

`just tests_and_coverage` runs the current test suite and reports coverage. Run `uv run -- pytest -m unit` for
the container-free unit-test tier. To discover focused recipes, run:

```console
just --list | grep -E 'test|coverage'
```

For a specific path, node ID, or other pytest argument, run `just pytest -- <arguments>` — always
include the leading `--`, mirroring `just podman -- <arguments>` below, since some pytest flags
(such as `-q` or `-v`) share a letter with `just`'s own short flags. Run `just lint` and
`just format` for repository quality checks, and run `just ci-lint` after changing GitHub Actions.

See the [CI validation cache inventory](docs/ci-validation-caches.md) for the tools run on GitHub Actions and their cache paths.

Run host Podman commands from the contributor container with `just podman -- <arguments>`.

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
just pytest tests/benchmark/real_server/test_cache_benefit.py
```

Its logged evidence, including any Atlas bandwidth evidence described below, lands in `pytest.log`
at the repository root; search that file for the test's name instead of scrolling the full suite's
output.

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

Before the first release, complete the [one-time PyPI publishing setup](docs/pypi-publishing-setup.md).

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
