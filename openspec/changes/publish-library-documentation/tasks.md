# Tasks

## 1. Documentation tooling and site

- [ ] 1.1 Add a released, Python-compatible Zensical dependency to a `docs` group in `pyproject.toml` and update `uv.lock`; verify `uv sync --locked --only-group docs` succeeds on the project interpreter without installing the library or development test dependencies.
- [ ] 1.2 Add `zensical.toml` with `docs_dir = "docs"`, `site_dir = "site"`, the canonical Pages URL from design.md, explicit local link/heading validation, responsive navigation, search, heading permalinks, code highlighting/copy controls, and light/dark palettes; verify its configuration is accepted by `uv run --locked --only-group docs -- zensical build --clean --strict` after task 2.2 repairs existing escaping links.
- [ ] 1.3 Add `just docs-serve` and `just docs-build` with the locked documentation group commands from design.md, confirm site/cache output is ignored, and exclude generated directories from Prettier, Markdownlint, and Lychee; verify preview starts without hosting credentials or MongoDB and build output stays untracked and outside formatter/link-checker inputs.
- [ ] 1.4 Add concise authoring/preview/build instructions to CONTRIBUTING, linking official Zensical documentation for framework details; verify both documented just commands run as written. Verify strict build rejection independently for missing local pages, assets, and heading targets using disposable configuration/source copies; if Zensical does not check assets, add a focused check to `docs-build` and cover its real valid/missing-target behavior.

## 2. Reader navigation and canonical content

- [ ] 2.1 Add `docs/index.md` with the library introduction, installation, current-default-branch label, README quick-start link, and routes to API, operations, performance, and repository examples. Add the secondary Maintainer reference and Research and decisions navigation sections with the exact existing pages listed in design.md; verify every navigation destination resolves, guides are not copied, and no `openspec/` or library source files appear in the site output.
- [ ] 2.2 Repair links escaping `docs/` across all rendered Markdown using explicit repository URLs for README, CONTRIBUTING, examples, source references, and benchmark reports; retain relative links between rendered guides and revision-pinned evidence where present. Verify a clean strict build and manually follow representative internal anchors and repository evidence links at the project subpath.
- [ ] 2.3 Add the hosted documentation URL to README and `[project.urls]`, retaining existing repository-readable guide links, and add one final-behavior Unreleased changelog entry; verify package metadata exposes Documentation and the URL agrees with site configuration.
- [ ] 2.4 Inspect the built site at approximately 375px and 1280px widths in both themes; verify keyboard navigation/search, heading permalinks, code copying, search results for `max_await_time_ms`, legibility, and no page-wide horizontal overflow. Record concise cold/warm strict-build timings and output size with reproduction commands for the implementation commit body, keeping raw output untracked.

## 3. Pull-request documentation gate

- [ ] 3.1 Add the documentation output to `scripts/ci_scope.py` for every input listed in design.md; extend the existing parametrized public-behavior cases in `tests/test_ci_scope.py` to cover docs/assets, TOML configuration, dependencies, recipes, both workflows, shared setup, and unrelated changes. Verify the scope command selects documentation correctly while retaining existing Python/format scope behavior.
- [ ] 3.2 Add a stable Documentation build job to `.github/workflows/test.yml` after scope/Prek/formatting, with conditional steps, read-only permissions, the existing setup action, and `just docs-build`; verify relevant PRs build, unrelated PRs keep a stable successful check, and failed quality gates prevent the build. Keep Markdown-only changes outside existing Python/database execution.
- [ ] 3.3 Document the new build check and its Prek/formatting prerequisites in CONTRIBUTING; inspect existing merge rules before recommending required-check changes, and verify the guidance does not claim that a skipped dependent job alone blocks merging.

## 4. Pages deployment and rollout

- [ ] 4.1 Add `.github/workflows/docs.yml` with relevant `main` push paths and manual redeploy, a read-only clean strict build and Pages artifact upload, and a separate `main`-only deployment using that artifact. Reuse setup pins, pin official actions to reviewed full SHAs, set timeouts, scope Pages/OIDC permissions only to deployment, use `github-pages`, and serialize deployments without cancellation; verify non-main manual runs and fork PRs cannot publish.
- [ ] 4.2 Add concise Pages publishing-source, environment-protection, redeploy, and rollback guidance to CONTRIBUTING with official GitHub references; verify local setup instructions need no personal token and configuration failures remain visible workflow failures.
- [ ] 4.3 Confirm public repository eligibility, Pages Actions source, and `github-pages` branch/environment protections before rollout. Complete required live setup within explicit user authorization; if authorization or administrator access is missing, record the exact blocker and leave this task open. Verify hosting uses the free standard project URL.
- [ ] 4.4 Once the reviewed implementation is available on `main` and live publication is authorized, run or observe the deployment and verify the deployed revision, HTTPS URL, search, mobile navigation, code controls, internal anchors, assets, and repository-only links. Record the deployed revision and outcome here; keep the change active if publication fails or cannot be verified.

## 5. Code Quality

- [ ] 5.1 Scan the entire files containing edited or added tests, including pre-existing tests, and ensure AGENTS.md Writing Tests guidelines are applied, including parametrization; verify the final test diff and whole-file audit conform.
- [x] 5.2 Confirm no new prose was added to code if implementing as Claude Code; inapplicable to this proposal because it was authored by OpenAI Codex. Reassess this task if implementation is performed by Claude Code.
