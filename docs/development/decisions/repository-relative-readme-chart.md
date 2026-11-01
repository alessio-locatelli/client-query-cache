# Keep README chart paths repository-relative

## Context

The README shows the [latency chart](../../../CONTRIBUTING.md#latency-chart) in light and dark variants selected by theme image fragments. The same README is the PyPI project description. PyPI resolves relative image paths against its own site, so repository-relative paths render as broken images there; PyPI also ignores the fragments and would show both variants even with working URLs.

The release process is manual, and the build backend (maturin) cannot rewrite README links when building a distribution.

## Decision

Keep repository-relative chart paths in the README and accept a broken chart image on PyPI. The chart is supporting evidence; the README text and links still work on PyPI, and the canonical chart lives in the repository and documentation site.

## Alternatives considered

**A separate PyPI README or build-time link rewriting.** maturin has no README transformation, and a second README would duplicate the README's content and drift from it.

**URLs pinned to the `main` branch.** PyPI would show the chart, but every published release page would change whenever `main` changes. Those pages could show measurements from unreleased code, and moving or renaming an asset would break all of them. On GitHub, branches and pull requests would show `main`'s chart instead of their own, and a new asset would be a broken image until merged.

**URLs pinned to the release tag.** Release pages would stay stable, but each release would need an extra step to rewrite the URLs. The version-bump commit would reference a tag that does not exist yet, so the README on GitHub would show broken images until the tag is pushed, and the link check would fail if the bump went through a pull request. A newly added asset would be broken until the next release, and GitHub's README would show the last release's chart rather than the current one.

**URLs pinned to the commit before the version bump.** This avoids the missing-tag window and the link-check failure, because the bump commit changes no chart files. It still needs a manual release step, and GitHub's README would still show the last release's chart rather than the current one.

## Consequences

The README on GitHub always shows the checked-out chart, chart changes are reviewable in pull requests, and releases need no README step. PyPI readers see a broken image in place of the chart.

This decision assumes that releases have no automation that can rewrite README links at build time without changing the repository's README.
