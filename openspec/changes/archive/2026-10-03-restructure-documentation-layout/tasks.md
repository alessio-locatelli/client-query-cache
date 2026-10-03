# Tasks

## 1. Establish the content boundary

- [x] 1.1 Verify the locked docs stack supports `pymdownx.snippets` with missing-file errors and Zensical page/anchor redirects. If redirects need a newer release, update only the docs-group Zensical requirement and `uv.lock`. Verify the supported configuration with a minimal local inclusion and redirect build; do not create a custom renderer or validator. Preserve the documented Zensical 404 skip-link defect and its issue URL, and recheck the generated 404 page after an upgrade.
- [x] 1.2 Before bulk moves, create a recoverable checkpoint and capture the headings of `docs/api-reference.md`, `docs/architecture.md`, and `docs/stream-cost-benchmarks.md` for redirect mapping. Move maintainer notes, the existing ADR, and research to the `docs/development/` destinations in design decision 2. Create its short index and repair incoming references, including CONTRIBUTING and contextual public-guide links. Verify each original section is preserved, important tracking/evidence URLs remain intact, and the new development index reaches each document.

## 2. Build the public guide hierarchy

- [x] 2.1 Create `docs/user/getting-started/installation.md`, `synchronous.md`, and `asyncio.md` from current README requirements and complete programs. Keep client/manager cleanup, supported topology, uncached fallback, and invalidation caveats accurate. Create `usage/cached-reads.md` and `usage/consistency.md` with concrete application examples and links to exhaustive API contracts. Verify both tutorials use the implemented public interfaces and can be followed from install to first cached read without opening GitHub prose.
- [x] 2.2 Move API guidance to `docs/user/reference/api.md`; split `docs/architecture.md` into `docs/development/architecture.md`, `docs/user/operations/deployment.md`, and `monitoring.md`, with a useful operations index. Follow the content map, retain public ownership/error/security/recovery/observability contracts, and correct the shared-budget statement against `CacheCore.__init__`. Verify each original substantive section has a destination and all public cross-links target the correct page and heading.
- [x] 2.3 Split workload evaluation and detailed measurements into `docs/user/benchmarks/index.md` and `stream-cost.md`; move guard administration to `docs/development/performance-regression-guard.md`. Move the chart to `docs/user/assets/`, preserve evidence URLs and revision pins, and keep reproduction commands and measurement limitations together. Verify every retained numerical claim still identifies its evidence and no benchmark results are regenerated or copied into new raw artifacts.
- [x] 2.4 Move the landing page to `docs/user/index.md` and provide audience, current-main notice, and clear site-local entry points. Shorten README according to the delta spec, linking directly to the hosted getting-started, benchmark, example, reference, and operations sections. Retain a labelled repository `examples/` source link to satisfy the active examples contract. Verify README has no parallel detailed tutorial or benchmark analysis and all detailed topics have canonical guide destinations.

## 3. Render examples from canonical files

- [x] 3.1 Keep `examples/README.md` as the command/prerequisite catalogue. Make its source and checkout links resolve in both GitHub and site contexts, and add labelled hosted integration links without copying instructions elsewhere. Enable checked, repository-relative snippets and include the catalogue in `docs/user/examples/index.md`, with a readable canonical-source link in the wrapper. Verify the rendered index contains commands, prerequisites, expected evidence, `MONGODB_URI`, and the database-reset warning rather than an external README substitute.
- [x] 3.2 Add hosted requests-cache, Celery, and py-abac pages that explain the integration's raw-write/cached-read boundary and include canonical program text in Python code blocks. Reconcile the delivered catalogue at apply time and use the same pattern for any additional already-delivered example. Link the hosted pages from the examples index/navigation. Verify included code matches the source revision and no example execution or third-party integration dependency is needed by `just docs-build`.

## 4. Wire navigation, redirects, and CI inputs

- [x] 4.1 Set `zensical.toml` to `docs_dir = "docs/user"`, remove the old development exclusions, and define the Home → Getting started → Usage → Benchmarks → Examples → Reference → Operations hierarchy. Configure legacy page/anchor redirects using the captured headings and design decision 4, including public destinations for former internal-design headings. Verify `just docs-build` resolves new local links and generated redirects under `/client-query-cache/`, with no development pages or OpenSpec material in output/search.
- [x] 4.2 Update `scripts/ci_scope.py` and `.github/workflows/docs.yml` to select `docs/user/**`, `examples/README.md`, and `examples/*.py` plus existing shared build inputs, replacing the old per-file exclusions. Update the existing parametrization in `tests/test_ci_scope.py` for public guides/assets, development notes/decisions/research, example prose/code, and mixed inputs. Verify `just pytest tests/test_ci_scope.py` shows guide-only/development-only Markdown does not select Python tests, example source selects both Python and documentation, and development-only changes do not select documentation. Inspect publication filters for matching canonical inputs while preserving main-only artifact deployment and permissions.
- [x] 4.3 Update CONTRIBUTING's documentation authoring section with the canonical-source locations, inclusion rules, source/evidence-link distinction, and existing preview/build commands. Add one final-behavior changelog entry. Search tracked references to moved filenames and repair mutable links, including ones in existing specs; preserve revision-pinned historical evidence and leave unrelated active-change plans intact. Verify links through the existing Lychee gate; report any references in the pinned specifications submodule without editing it.

## 5. Inspect the complete reader journey

- [x] 5.1 Inspect the clean local preview through installation, both tutorials, usage, benchmarks, every delivered integration, reference, and operations. Exercise full-text search for `max_await_time_ms`, keyboard/mobile navigation, both appearances, code copying, and every captured legacy guide/heading URL. Verify learning navigation stays on the site, source/evidence links are labelled, and development prose is absent from output/search. Record any unresolved discrepancy rather than treating a strict build as proof of usability.

## 6. Code Quality

- [x] 6.1 Scan the entire edited `tests/test_ci_scope.py` and any other edited test file, including pre-existing tests, and apply AGENTS.md Writing Tests guidelines, including parametrization. Verify the existing subprocess-based public-behavior checks remain shared rather than duplicated.
- [x] 6.2 If you are Claude Code, confirm that no new prose was added to code and rationale remains in specs and commit bodies. Inapplicable to this Codex-authored plan; OpenAI Codex is exempt.

## Verification evidence

The locked strict build and default formatting/link/lint gates succeeded with all new files staged.
Snippet-only Python fences use Ruff’s supported Markdown formatting comments to preserve
inclusion directives; the canonical Python programs remain subject to their normal checks. The existing CI-scope
parametrization passed with the new canonical-input cases. Headless Chromium inspected the local
preview through all 16 public pages, nine README/catalogue entry links, three legacy page routes,
and all 35 captured legacy heading URLs. Included programs matched their canonical source text;
copying preserved the program. Keyboard navigation reached the API guide, and searching
`max_await_time_ms` opened its await-time section. Mobile navigation and search reached the API;
all public pages avoided page-wide horizontal overflow at 390 pixels. Light and dark appearances,
code readability, heading destinations, and labelled source/evidence links were inspected.
Development documents were absent from generated output and their title searches returned none.

Live publication was not exercised. The accepted Lychee exclusion for unpublished section routes
and the existing Zensical 404 skip-link defect are recorded in
`docs/development/ci-validation-caches.md` under “Documentation validation limitations”.
Browser diagnostics and generated site output remain untracked. No runtime benchmarks were
regenerated because the change does not modify cache execution.
