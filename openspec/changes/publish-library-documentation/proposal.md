# Proposal

## Why

The library's API and operations guides are available as repository Markdown, but readers have no dedicated documentation site with search and navigation. Publishing those guides makes the library easier to discover, evaluate, and use without adding a paid service or a complex authoring toolchain.

## What Changes

- Build a static documentation site with Zensical, using the existing Markdown guides as canonical sources and a small new landing page.
- Host the site on GitHub Pages at `https://alessio-locatelli.github.io/client-query-cache/`, assuming the repository is public and Pages can be enabled with GitHub Actions as its publishing source.
- Provide responsive navigation, full-text search, light/dark themes, readable code blocks, and a clear route from installation to API and operations guidance.
- Add locked documentation tooling and simple local preview/build commands using the existing uv and just toolchain.
- Validate relevant documentation changes in pull requests and deploy the built artifact after relevant changes reach `main`, with a manual redeploy option restricted to `main`.
- Preserve repository-readable documentation and repair links and assets for the project's Pages subpath. Link examples and benchmark evidence to their repository sources rather than copying them into the site.
- Add the documentation URL to the README and package metadata, plus concise contributor instructions for authoring and publishing.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `public-library-documentation`: make the public guides available as a free, searchable, responsive site with reproducible local preview and build commands.
- `continuous-integration`: validate documentation-site inputs on pull requests and publish only trusted default-branch builds through a separate deployment job.

## Impact

- Expected implementation files: `zensical.toml`, `docs/index.md`, existing public guides, `pyproject.toml`, `uv.lock`, `justfile`, `.gitignore`, formatting exclusions, `scripts/ci_scope.py` and its existing tests, `.github/workflows/test.yml`, a new `.github/workflows/docs.yml`, README, CONTRIBUTING, and CHANGELOG.
- Zensical belongs in a dedicated documentation dependency group; it adds no library runtime dependency or MongoDB requirement for site builds.
- Repository administration must confirm public visibility, enable Pages using Actions, and inspect the `github-pages` environment and relevant merge rules. Live configuration and publication are implementation steps requiring explicit authorization for those external actions.
- This change publishes current default-branch documentation; release-version selectors, custom domains, generated API documentation, hosted pull-request previews, analytics, and a broad documentation rewrite are outside scope.
- The existing `add-real-usage-examples` change continues to own new example programs. This change links its checked-in documentation without depending on completion of its blocked targets.
