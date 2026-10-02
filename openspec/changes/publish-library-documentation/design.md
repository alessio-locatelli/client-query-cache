# Design

## Context

See [proposal.md](proposal.md) for motivation and scope. The checkout has canonical Markdown guides in `docs/`, runnable integrations under `examples/`, and a README quick start. There is no site generator configuration or documentation deployment workflow. `pyproject.toml` declares Python 3.14.6 or newer, uv manages the committed lockfile, and just provides contributor commands.

The existing pull-request workflow always starts and uses `scripts/ci_scope.py` to select validation tiers. Its Prek and formatting jobs gate expensive work. The shared setup action installs uv, Python, and just. The active executable-pin automation change owns broader pin-update policy; this change uses the existing dependency and action update mechanisms without extending that change's scope.

Guides link outside `docs/`: the README, contributor instructions, example programs, and retained benchmark evidence. Using the repository root as the site's source would expose unrelated files and require broad exclusions. Copying every referenced file would create duplicate sources and unnecessary output.

## Goals / Non-Goals

**Goals:** Keep authoring in Markdown; make preview and strict builds deterministic; reuse existing quality gates and setup; publish one static artifact under the repository's Pages subpath; keep publishing permissions away from pull-request code.

**Non-Goals:** No runtime package changes, database-dependent documentation builds, framework plugin ecosystem, custom frontend application, release-version documentation storage, or execution of example programs during site builds. The proposal defines the remaining scope exclusions.

## Decisions

### Use Zensical with GitHub Pages

Zensical provides the requested modern documentation interface while retaining Markdown and the Python toolchain. Its [installation guide](https://zensical.org/docs/get-started/) documents uv integration, and its [publishing guide](https://zensical.org/docs/publish-your-site/) documents GitHub Actions artifact deployment. [GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages) is free for public repositories and provides the project URL without buying a domain.

Alternatives considered: Sphinx is well suited to generated Python references but would add an authoring/theme setup for already-written Markdown; a JavaScript framework such as Docusaurus would add a second application build stack. Cloudflare Pages and Read the Docs are possible static hosting alternatives, but would introduce another service connection when the repository already uses GitHub Actions. They are not required to satisfy this proposal.

Select and lock a released Zensical version compatible with the pinned project interpreter during implementation. Do not depend on an unpinned package installation or assume arbitrary MkDocs plugins work: Zensical documents [specific compatibility behavior](https://zensical.org/docs/compatibility/mkdocs/plugins/). Keep the existing hand-written API reference.

### Render the existing documentation directory directly

Add root `zensical.toml` with `docs_dir = "docs"`, `site_dir = "site"`, and canonical `site_url = "https://alessio-locatelli.github.io/client-query-cache/"`. Never point the generator at the repository root or enable submodule checkout.

Create `docs/index.md` as a concise library introduction with installation, current-default-branch labeling, and routes to the existing guides. Keep complete quick-start programs in the README, linked from the landing page, rather than maintaining a second copy. Primary navigation is Home, API reference, Architecture and operations, Performance, and Examples; Examples points to the repository's `examples/README.md`. A secondary Maintainer reference section includes `pypi-publishing-setup.md` and `ci-validation-caches.md`; a secondary Research and decisions section includes `causal-invalidation-barrier-research.md` and `decisions/defer-causal-invalidation-barrier.md`. These are already repository-public documents and are published from their existing sources without a substantive rewrite. The exclusion of planning artifacts refers to `openspec/`, which lies outside `docs_dir` and is never site input.

Use relative Markdown links between rendered guides. Replace links escaping `docs/` with explicit GitHub `blob/main` or `tree/main` URLs, preserving heading fragments. Keep already versioned evidence links pinned to their recorded revisions. Do not rewrite existing evidence to claim a newer library measurement. Add a Documentation link in README and `[project.urls]`, retaining repository-readable guide links.

Use the built-in theme, responsive navigation, search, heading permalinks, code highlighting/copy controls, and the documented [appearance toggle](https://zensical.org/docs/setup/colors/). Prefer stock styling with restrained project colors; avoid custom JavaScript or a template fork. Keep fonts and theme assets local where supported, with no analytics service. Verify the existing benchmark SVG is legible in both themes before displaying it on the landing page.

### Isolate and lock documentation tooling

Add a `docs` dependency group containing Zensical and update `uv.lock`. Provide `just docs-serve` and `just docs-build` using `uv run --locked --only-group docs -- zensical serve` and `uv run --locked --only-group docs -- zensical build --clean --strict`. An installed project is unnecessary because the reference is Markdown. Confirm these exact commands with the selected release before recording them in CONTRIBUTING.

Enable the documented [link and heading validation](https://zensical.org/docs/setup/validation/) explicitly. Confirm that strict builds also reject missing local assets; if the selected release does not enforce this, add a focused asset-target check to the same build entry point rather than weakening the requirement. Do not disable validation to accommodate unresolved links.

Until the first deployment, the canonical Pages URL returns 404. With maintainer
approval, Lychee temporarily excludes only that exact URL so the implementation
can pass its pre-publication quality gates. Remove the exclusion after successful
live verification and rerun link checking; local page, heading, and asset validation
remains enabled throughout rollout.

The repository already ignores `site/`; confirm Zensical's cache directory is ignored too. Exclude generated output from Prettier, Markdownlint, and link checking so subsequent validation does not crawl build artifacts. Dependency download caches may be reused through the existing setup action; do not persist Zensical's build cache in CI. Its [build documentation](https://zensical.org/docs/usage/build/) recommends clean builds while caching behavior evolves.

### Add pull-request site validation to the existing workflow

Extend `scripts/ci_scope.py` with a documentation scope output and its existing parametrized regression cases. Inputs are `docs/**`, `README.md`, `examples/README.md`, `zensical.toml`, `pyproject.toml`, `uv.lock`, `justfile`, the scope script, `.github/workflows/test.yml`, `.github/workflows/docs.yml`, and `.github/actions/setup-toolchain/**`. Include any new shared build/check script if one becomes necessary. Source changes alone do not trigger site generation because API docs are not generated from code.

Add a stable Documentation build job in `test.yml`, depending on scope, Prek, and formatting. Put the scope condition on its build steps so irrelevant changes still yield a stable successful job. Reuse the shared setup action and run `just docs-build`. Keep its token read-only and credentials unpersisted. Do not create a separate PR workflow that duplicates lint and formatting or use `pull_request_target`.

Metadata, lockfile, recipe, and CI changes still trigger the existing Python gates. Markdown-only guide changes retain the existing database-free validation scope. If Documentation build is made a required check, independently require Prek and formatting as well, since a job skipped after failed prerequisites must not permit merging.

### Deploy from a separate trusted workflow

Add `.github/workflows/docs.yml` for relevant `push` events on `main` and `workflow_dispatch` for redeploying `main`. Use equivalent site-input paths, including the deployment workflow itself and shared build/toolchain inputs. This workflow is not a required PR check, so workflow-level push path filtering is appropriate.

The build job checks out the event revision with credentials disabled, reuses pinned setup, runs the same clean strict build, and uploads only `site/` with the Pages artifact action. This post-merge build validates the actual revision being published and is not a rerun of broad package/database gates. It uses read-only repository permissions.

The deployment job depends on that build, runs only for `refs/heads/main`, uses the `github-pages` environment, and promotes that run's artifact with the official Pages actions. Limit `pages: write` and `id-token: write` to this job; use no personal access token or third-party hosting secret. Configure Pages without automatically enabling it through CI. Pin actions to reviewed full SHAs, set job timeouts, and reuse existing tool pins rather than inventing another version policy.

Serialize the deployment job with a site-specific concurrency group and `cancel-in-progress: false`. Reject non-main manual runs at the job condition before requesting publishing permissions. Report the deployment action's `page_url` through the environment. A failed build stops deployment; a hosting setup or deployment error remains a visible failure. Do not download artifacts from untrusted pull-request runs.

### Verify usability and resource costs at implementation time

Build once per relevant PR revision and once for the actual default-branch publication revision. Work scales with documentation text and bundled assets; there are no application database calls or backend services. Dependency installation and rendering are expected to dominate contributor/runner time, but no timing claim is established yet.

Inspect the built site at its project subpath at approximately 375px and 1280px viewport widths, in both appearances and with keyboard navigation. Exercise search for `max_await_time_ms`, internal heading links, repository evidence links, and code copying. Verify missing page, asset, and heading targets independently produce strict-build failures with disposable inputs outside tracked sources. Record a concise cold/warm build-duration and output-size measurement with reproduction commands in the implementation commit body; retain no raw diagnostics in Git. Runtime cache benchmarks are irrelevant because library execution is unchanged.

## Risks / Trade-offs

- [Repository hosting eligibility is unverified] → Confirm public visibility and Pages availability before the live rollout. Do not substitute a paid plan silently.
- [Zensical behavior evolves] → Lock a compatible release, use clean strict builds, and inspect rendering after dependency upgrades.
- [Repository-only links break under the Pages subpath] → Convert escaping links explicitly and check rendered destinations, assets, and anchors.
- [Default-branch docs differ from installed releases] → Label the site as current default-branch documentation and avoid a misleading version selector.
- [Publishing can fail despite a successful local build] → Treat Pages activation and environment permissions as separate rollout prerequisites; report the failed deployment and keep the change active until publication is verified.
- [Secondary research and maintainer pages distract readers] → Keep task-oriented public guides in primary navigation and label secondary material clearly without rewriting it in this change.

## Migration Plan

1. Implement local tooling, configuration, navigation, link repairs, and PR build coverage on the documentation feature branch.
2. Inspect repository visibility, Pages publishing source, `github-pages` environment protections, and merge rules. Document required administrator actions in CONTRIBUTING with links to official GitHub instructions.
3. Obtain explicit authorization for live Pages configuration/publication before changing those external settings. Enable Pages with Actions as the publishing source when authorized; do not change unrelated repository rules.
4. After the reviewed implementation reaches `main`, deploy through the publishing workflow and verify HTTPS, navigation, search, assets, and representative deep links at the actual project URL. Record the deployed revision and outcome in the change's tasks.
5. To roll back, revert the site change and redeploy a known-good `main` revision. If no prior site exists, disable the new publishing workflow and Pages hosting when authorized. Existing repository Markdown remains available throughout.
