## Context

The current single workflow starts quality, package, and database-backed jobs for every pull request and
uses a full-history Git checkout plus a shell classifier to conditionally skip the database tier. See
proposal.md for motivation and the continuous-integration delta for the behavior contract.

## Goals / Non-Goals

**Goals:**

- Select independent hosted validation tiers with native pull-request path filters.
- Preserve the established validation surfaces without running Prettier twice.
- Avoid database containers and package installation for documentation-only changes.

**Non-Goals:**

- Change local contributor commands or the test suite.
- Add a third-party path-filter action or conditionally enforce merge policy.

## Decisions

- Replace the monolithic workflow with `prek.yml`, `prettier.yml`, and `test.yml`. Each workflow owns one
  concern, has its own cancellation group, and shares the existing setup composite where Python tooling is
  required. A single workflow with a custom Git diff is removed because GitHub Actions natively evaluates
  path filters before scheduling a workflow.
- Run `prek run --all-files --skip prettier` and the existing Justfile format check in the always-on
  workflow. The formatting workflow owns the local Prettier hook's equivalent `npm run format:check`,
  which also retains Markdownlint validation. Running both on every pull request would duplicate the same
  full-tree formatter work.
- Trigger formatting for the repository's Prettier-formatted Markdown, JSON/JSONC, and YAML files plus its
  formatter configuration. Trigger Python validation exclusively for `**.py`, `pytest.ini`, `pyproject.toml`,
  and `uv.lock`, as requested.
  The test workflow keeps package-artifact and Docker-backed coverage jobs separate so they remain parallel.

## Resource Profile

```text
documentation-only pull request
  -> Prek                    full tracked tree, no Node install
  -> Prettier + Markdownlint changed formatting scope, Node dependency install
  -> no package build
  -> no Docker-backed coverage

Python/configuration pull request
  -> Prek                    full tracked tree
  -> package validation      locked dependency sync, build, two isolated imports
  -> coverage                locked dependency sync, one disposable Docker replica set
```

The supplied documentation-only runs measured 5 seconds for classification, 74 and 128 seconds for the
quality/package job, and 51 and 40 seconds for Docker-backed coverage. The post-change hosted timing
cannot be measured before this unpushed configuration is executed; the native filter guarantees that the
package and Docker jobs are not scheduled for the documented path set.

## Risks / Trade-offs

- [A test-relevant non-Python file changes] -> The path set deliberately follows the requested Python and
  declared test-configuration inputs; expand it only with a concrete additional runtime input.
- [A Prettier-supported extension is introduced] -> Maintain the explicit formatter path list alongside
  the configured formatter invocation.
- [A path-filtered workflow is made required later] -> GitHub leaves an absent filtered workflow pending;
  revisit merge policy before requiring a conditionally triggered workflow.

## Migration Plan

1. Add the three workflows and remove the monolithic workflow in one commit.
2. Validate workflow syntax and CI policy locally.
3. Let the next pull requests exercise the native filters; restore the previous workflow from the commit if
   a required-check policy makes a filtered workflow unsuitable.
