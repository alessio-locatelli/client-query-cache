# Design

## Context

See [proposal.md](proposal.md) for motivation. The current site uses Zensical 0.0.67, `docs/user/`, canonical example snippets, strict local builds, and GitHub Pages artifact deployment. `.github/workflows/docs.yml` runs on relevant `main` changes or manual dispatch. Package publication creates a draft GitHub Release, uploads to PyPI, then publishes the GitHub Release; a tag alone does not prove publication succeeded.

The existing public-documentation spec explicitly describes default-branch-only content. This change replaces that obligation with two clearly identified editions. GitHub’s latest published stable release is currently `v0.2.0`; `git diff v0.2.0..HEAD -- src/client_query_cache pyproject.toml uv.lock` was empty during planning. Its documentation predates the new layout, so initial stable publication needs a reviewed documentation-only backport.

[Zensical’s supported versioning integration](https://zensical.org/docs/compatibility/mkdocs/mike/) is the maintained mike fork. Revision `2d4ad799442f4592db8ad53b179bfb33db8c69ac` supports TOML configuration and builds with `MIKE_DOCS_VERSION`; its CLI invokes a clean Zensical build. [Footer navigation](https://zensical.org/docs/setup/footer/) uses `navigation.footer`.

## Goals / Non-Goals

**Goals:** Tie stable content to the published package, keep development independent, and reuse the existing theme and artifact deployment.

**Non-Goals:** Historical version archives, runtime changes, package publication during apply, custom version-selector/search UI, or a production MongoDB tutorial. A pre-commit badge is optional decoration and adds no required information; the Python badge is the requested prerequisite replacement.

## Decisions

### 1. Two mutable edition routes, with stable as the default

Use `/client-query-cache/stable/` and `/client-query-cache/dev/`, with exactly two selector entries: `Latest release (X.Y.Z)` and `Development (main)`. Use mike’s version metadata, titles, default-version redirect, and Zensical selector. Do not retain numbered edition directories. Search indexes, local links, bundled assets, and snippets belong to each edition.

Remove the home-page warning that installed options may differ. The selector identifies the edition; development gets a short `main` identity where needed. README and package metadata use the default stable entry point. Preserve root-level direct page and heading links, including the three legacy guides, through Zensical’s existing redirect mechanism; root redirects target stable guidance. Preserve fragments explicitly where legacy headings moved. Edition switching uses the framework’s same-page behavior and its landing-page fallback.

A single default-branch site would retain the reported mismatch. Per-release archives would add maintenance and storage beyond the two requested editions.

### 2. Release provenance and a bounded bootstrap backport

Resolve stable identity from the latest published, non-draft, non-prerelease GitHub Release after the existing successful PyPI workflow. Fetch its exact tag commit. Normal stable builds use that tag’s docs, examples, and package metadata; development uses a captured `main` commit. Never select the most recent local Git tag or borrow current development examples for stable builds.

For the initial `v0.2.0` edition, record one immutable documentation correction commit in a small root `stable-docs.toml`, keyed by that release tag. Produce that commit from reviewed documentation/layout/UX corrections while keeping `src/client_query_cache`, executable examples, and runtime `[project]` metadata identical to the tag. Resolve and compare those inputs before accepting the backport. Record both release and docs source commits in build diagnostics; show the package version in the UI. An uncommitted worktree or moving branch is not a stable source.

The backport includes the corrected guide hierarchy and reader-experience prose, so stable users get the installation journey immediately. Future release tags containing this layout need no override; the record applies only to its exact tag and must not become a second manually copied guide tree. Documentation-only future corrections can replace the immutable record after the same review and compatibility checks. Do not rewrite package release tags or publish a new package solely for prose fixes.

### 3. Artifact publication using established versioning commands

Pin the mike fork in the docs dependency group and lockfile. Add a small orchestration command in `scripts/build_versioned_docs.py` and a `just docs-build-editions <stable-tag>` entry. It checks out the two resolved source snapshots into disposable directories, runs the maintained versioning CLI against a local generated Git branch, then exports the complete site into an untracked artifact directory. Generated commits/metadata are build artifacts, not source commits or a remote deployment branch.

The orchestrator owns source selection, normalized edition-specific configuration, and artifact assembly. Mike owns version metadata and default selection; Zensical owns rendering and redirects. Normalize the existing TOML configuration with version-provider settings and strict mode. Prove that strict failures propagate through mike; if its CLI cannot honor configuration strict mode, perform the existing strict build before the CLI build rather than weaken validation. No custom renderer, selector, link validator, or per-page HTML rewriting is needed.

Render stable source/checkout links against the recorded stable source revision instead of `main`; preserve explicitly pinned benchmark evidence. Shared publishing settings may adapt release configuration without replacing release prose/code with development content. Root redirect output uses the existing Zensical redirect configuration and is included in the same artifact.

Keep `just docs-serve` and `just docs-build` as the fast working-tree authoring commands. The combined command takes an explicit locally available stable tag; it does not require hosting credentials or MongoDB. Document how to serve its output for version-selector inspection.

### 4. Release completion triggers the same serialized publisher

Extend the existing docs workflow with successful completion of `Publish to PyPI`, using `workflow_run`, because publishing the GitHub Release with the repository token does not itself trigger another workflow. The controller always checks out trusted `main`, resolves current latest stable release, and builds both source snapshots. Ignore failed/cancelled upstream runs; do not execute code or consume artifacts from the triggering run. Keep relevant `main` path triggers and main-only manual repair.

Use the same `documentation-publication` concurrency group, without cancelling state changes. Keep read-only contents permissions for source/build jobs and Pages/OIDC elevation only in deployment. Upload one complete Pages artifact only after both edition builds and root redirects succeed. Do not publish a partial edition or advance stable on draft/tag creation. Existing package publishing and approval semantics stay intact.

Select the orchestration script, edition configuration, versioning dependency files, canonical docs/examples, and existing shared inputs consistently in PR validation and publication. Development-only Markdown stays outside site inputs. PRs verify artifact assembly against local release snapshots without making deployments or querying mutable release identity.

### 5. Prose and local setup changes

- Delete the installation page’s repeated product paragraph and “First cached read” section. Keep substantive prerequisites and asynchronous-consistency guidance in their canonical guides.
- Delete the tutorials’ “First install” reminders and generic “Continue with” endings. Enable `navigation.footer`; preserve contextual links that explain the current page’s code or limits. Keep installation → synchronous → asyncio as the documented reading order; async remains independently reachable in navigation.
- Replace “effective caching” everywhere in public prose with `Caching requires MongoDB 8.0+ on a replica set or sharded cluster.` Explain below the requirements that older MongoDB versions and standalone servers execute uncached reads. Remove the sentence merely restating PyMongo deployment support.
- In README, show a Python badge labelled `Python 3.14.6+`, matching `requires-python`, instead of the long sentence. Retain the topology prerequisite and asynchronous caveat, and link the prerequisite to hosted requirements. Do not imply Python 3.14.0 satisfies a 3.14.6 floor.
- Add “Local MongoDB” to installation. Link the checkout’s `docker-compose.yaml` as an example single-member replica set and give concise project start/readiness/stop commands. The existing file runs `mongod --replSet rs0`, publishes port 27017, and initializes `localhost:27017` through `mongo_helper`. Verify helper completion and writable-primary readiness before presenting the tutorial URI. Link official Compose documentation for tool installation; keep warnings about disposable tutorial data concrete.

## Resource costs

Each publication renders two small documentation snapshots and root redirects. CPU/disk work scales with the two guide corpora and included programs; release discovery is one GitHub API lookup plus exact-ref fetches. There is no cache-runtime cost or database access. Dependency download and Git fetch are expected to dominate cold CI runs; this is an estimate, not a measured result. Record combined build time and output size during apply. The CLI strict-build fallback may add two renders if necessary; prefer native strict configuration when supported.

## Risks / Trade-offs

- The mike fork is a transitional Git dependency → pin its commit and use its documented interface; prove locked Zensical compatibility before expanding publication.
- A documentation backport could claim an unreleased API → require immutable provenance and matching runtime/example/project metadata; fail visibly on mismatch.
- Adding edition prefixes can break existing direct URLs → verify every current direct entry and legacy heading in the assembled artifact.
- A delayed successful older release run could arrive after a newer release → resolve the current latest published stable release at execution time; use the shared deployment queue.
- Selector behavior or strict configuration may differ in the locked theme → use a minimal two-edition compatibility probe and browser inspection rather than assume upstream examples prove local behavior.
- The Compose helper’s current unconditional initialization may report an error on a repeated start → document commands only after checking actual startup/readiness behavior; fix a reproduced project setup defect within this change and record it in the active tasks.
- Lychee’s accepted unpublished-route exclusions and Zensical’s known 404 skip-link defect remain → carry their documented limitations forward; do not treat local assembly as evidence of live deployment.

## Migration Plan

Prepare and review the documentation-only `v0.2.0` backport, configure its immutable source, and inspect both editions locally. Merge publication changes through the normal review path. The first ordinary main/manual deployment publishes the combined artifact with stable default and development available. Inspect the live default, selector, direct links, and footer after publication. Roll back through a reverted workflow/configuration and a complete previously working Pages artifact; retain package release tags and source provenance.
