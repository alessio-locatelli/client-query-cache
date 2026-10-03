# Design

## Context

See [proposal.md](proposal.md) for motivation. `zensical.toml` currently builds all of `docs/`, excludes five maintainer/research paths individually, and exposes four local pages plus an external examples entry. `docs/index.md`, the API guide, and the operations guide send tutorial readers to README. README owns the only complete synchronous and asyncio quick starts.

`docs/architecture.md` combines private-component diagrams and invalidation mechanics with important public operating limits. `docs/stream-cost-benchmarks.md` combines workload evaluation, retained measurements, reproduction commands, and pull-request guard administration. Documentation exclusions are duplicated in Zensical, `.github/workflows/docs.yml`, and `scripts/ci_scope.py`; existing selection coverage is in `tests/test_ci_scope.py`.

The active examples change owns three delivered integrations (requests-cache, Celery, and py-abac), additional unfinished targets, and a contract requiring a command catalogue in `examples/README.md`. This restructure consumes the delivered files and leaves executable integration work with that change. The current public-documentation spec permits external-only examples and requires both levels of architecture in documentation; the delta explicitly revises those expectations.

## Goals / Non-Goals

**Goals:**

- Make the publishing boundary structural, with canonical topic ownership and a predictable place for future content.
- Distinguish tutorials, operational how-to guidance, benchmark interpretation, reference, and internal engineering material.
- Preserve technical limits, source provenance, and meaningful existing public links during the move.

**Non-Goals:**

- Changing runtime APIs, cache semantics, benchmark runners, or third-party adapters.
- Finishing blocked examples, introducing release-versioned documentation, redesigning branding, or changing hosting settings.
- Publishing private library modules, OpenSpec artifacts, full research notes, or maintainer setup procedures.

## Decisions

### 1. Publish only `docs/user/`

Set `docs_dir = "docs/user"`. Place maintainer documentation in `docs/development/`, with `decisions/` and `research/` beneath it. This prevents a newly added development note from entering published output merely because someone forgot an exclusion. Remove the old per-file exclusion list once all its documents have moved.

Target organization:

```text
docs/
  user/
    index.md
    getting-started/
      installation.md
      synchronous.md
      asyncio.md
    usage/
      cached-reads.md
      consistency.md
    benchmarks/
      index.md
      stream-cost.md
    examples/
      index.md
      requests-cache.md
      celery.md
      py-abac.md
    reference/
      api.md
    operations/
      index.md
      deployment.md
      monitoring.md
    assets/
      benchmark-latency-light.svg
  development/
    index.md
    architecture.md
    performance-regression-guard.md
    pypi-publishing-setup.md
    ci-validation-caches.md
    executable-version-updates.md
    decisions/
      defer-causal-invalidation-barrier.md
    research/
      causal-invalidation-barrier.md
```

Use existing Zensical hierarchy and theme features. The navigation order is Home → Getting started → Usage → Benchmarks → Examples → Reference → Operations. Give installation and operations pages concrete next-step links; do not add empty section indexes simply to match a template. `docs/development/index.md` is a short directory entry point linked from CONTRIBUTING.

Alternative: keep `docs_dir = "docs"` with a development exclusion glob. It can work but leaves publication dependent on an exclusion convention rather than the content root. A replacement framework adds migration costs without solving topic ownership.

### 2. Assign every substantive topic one canonical destination

| Current source/content                                            | Canonical destination and disposition                                                                                                                  |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `docs/index.md`                                                   | `docs/user/index.md`: product overview, audience, current-main notice, and site-local learning paths                                                   |
| README requirements and install                                   | `getting-started/installation.md`: full compatibility and topology guidance; README retains only essential prerequisites and install command           |
| README synchronous/asyncio programs                               | `getting-started/synchronous.md` and `asyncio.md`: complete programs with lifecycle and next steps; remove detailed programs from README               |
| README cached-read explanations                                   | `usage/cached-reads.md`: raw/cached handles, six methods, list results, filters/sort/collation, and links to exact reference contracts                 |
| Consistency and raw-read guidance in README/architecture          | `usage/consistency.md`: eventual invalidation, read-after-write caveats, bypass behavior, and manager isolation                                        |
| `docs/api-reference.md`                                           | `reference/api.md`: complete signatures, options, limits, errors, diagnostics, and ownership contract; retain useful heading names                     |
| Architecture system requirements                                  | Installation page; other pages link there                                                                                                              |
| Architecture internal diagrams and low-level design               | `docs/development/architecture.md`: internal architecture with links to public behavior contracts                                                      |
| Architecture retry/recovery/security/pool/capacity guidance       | `operations/deployment.md`: practical deployment guidance; public explanation uses application-level concepts                                          |
| Architecture observability/OpenTelemetry/health guidance          | `operations/monitoring.md`: practical monitoring and instrumentation, linked from API diagnostics                                                      |
| `docs/stream-cost-benchmarks.md` workload evaluation              | `benchmarks/index.md`: evaluation factors, illustrative chart and its evidence, comparison limits, link to detailed measurements                       |
| Benchmark reports, costs, await-time and compression measurements | `benchmarks/stream-cost.md`: interpretation and reproduction with existing evidence links and provenance                                               |
| Benchmark pull-request guard administration                       | `docs/development/performance-regression-guard.md`; public benchmark pages link only if context calls for it                                           |
| `examples/README.md`                                              | Remains the canonical catalogue, prerequisites, commands, expected outcomes, and destructive-database warning; include it in the site's examples index |
| Delivered `examples/*.py`                                         | Remain canonical executable sources; include source in hosted integration pages, with short integration-specific explanations                          |
| `docs/assets/benchmark-latency-light.svg`                         | `docs/user/assets/benchmark-latency-light.svg`; keep one asset and update README's reference if retained                                               |
| Publishing/cache/version-update notes                             | Move unchanged in substance to `docs/development/` and update CONTRIBUTING links                                                                       |
| Existing decision and barrier research                            | Move to development decisions/research locations; preserve provenance, tracking URLs, and decision semantics                                           |

Short summaries repeated at entry points are acceptable; full tutorials, tables, exact parameter contracts, and measurement explanations are not duplicated. Tutorials explain how to use a feature and link to its exhaustive reference. Both plain repository readers and site readers can reach canonical source files. Source wrappers carry a readable link to the included file for repository readers.

The operations guide currently claims that the shared memory budget scales with active database count. `CacheCore.__init__` constructs one `WeightedLru` from `shared_budget_bytes` for a manager. Correct the public statement: stream count scales per active database, while one configured budget is shared within a manager; additional managers/processes multiply independent budgets. Preserve other important claims only after checking their existing implementation or retained evidence during editing.

Alternative: leave README as the complete tutorial and include it wholesale on the site. That keeps one file but also keeps the overloaded README, redundant site overview, and poor topic boundaries. Independently copying its examples creates maintenance drift.

### 3. Reuse example prose and code at build time

Use `pymdownx.snippets`, documented by [Zensical's code-block guidance](https://zensical.org/docs/authoring/code-blocks/#embed-external-files), to include canonical `examples/README.md` in `docs/user/examples/index.md` and each delivered program in a fenced Python block on its integration page. Set repository-relative inclusion paths and missing-file checks using the extension's supported configuration. Builds read text only: they never import or run the examples and still need no MongoDB, Docker, credentials, or third-party integration packages.

Make canonical examples README links unambiguous when rendered in either context: explicit GitHub links for source files and checkout prerequisites, and site URLs for hosted explanations. Readers learn the integration on the site and follow clearly labelled source links only when they want a checkout or executable file. Keep commands, `MONGODB_URI`, isolated-environment behavior, expected evidence, and the database-reset warning in the canonical catalogue. Integration pages explain adapter choices and raw-write/cached-read boundaries without repeating that catalogue.

Preserve the active examples change's command-list requirement. Only delivered examples are published; unfinished or blocked integrations have no empty site pages. If that change delivers another integration before implementation begins, add its matching hosted page and navigation entry in the same pattern without taking ownership of its Python implementation.

Alternative: move all example instructions to the site and make `examples/README.md` only a pointer. That conflicts with the active examples specification. A custom copy/rewrite script duplicates capabilities already supplied by the documentation stack.

### 4. Preserve public URL destinations using redirects

Keep the project root URL unchanged. Configure page and anchor mappings through Zensical's [redirects support](https://zensical.org/docs/setup/redirects/):

- `api-reference.md` → `reference/api.md`, preserving its current headings.
- `stream-cost-benchmarks.md` → `benchmarks/stream-cost.md`; map the workload-fit heading to `benchmarks/index.md` and guard-administration heading to a public benchmark explanation.
- `architecture.md` → `operations/deployment.md`; map system requirements to installation, consistency to the usage guide, and monitoring headings to operations/monitoring.
- Map former internal-design headings to a concise public explanation of the cache's behavior in usage guidance, with an optional development-source link. Do not expose the internal guide to maintain a bookmark.

Inventory every existing heading in those three guides before splitting them and add explicit mappings wherever its content moves. Redirects contain no duplicated guides, stay out of primary navigation, and land inside the site. Existing asset URLs can change after all repository references are updated; no asset compatibility copy is proposed.

Validate the documented support against the locked Zensical version before implementation. If the lock lacks the required redirects capability, update only the docs-group framework version and lock to a release providing it; do not introduce a custom redirect generator. Link headings within new pages directly rather than depending on legacy redirects.

### 5. Align validation and publication with actual inputs

In `scripts/ci_scope.py` and `.github/workflows/docs.yml`, replace individual internal-document exclusions with selection of `docs/user/**`, `examples/README.md`, and `examples/*.py`, alongside the existing site configuration, dependencies, recipes, workflow, and shared-toolchain inputs. Keep development-only Markdown on ordinary prose checks without selecting documentation builds. Remove stale test cases for old paths and extend the existing parametrization for public/development content, assets, included example instructions, and included Python source.

Preserve stable documentation-check names, lint/format prerequisites, main-only deployment, serialized publication, and artifact identity. Python example changes keep their existing Python validation in addition to selecting documentation; public Markdown changes do not gain database tests. The shared scope script remains a PR-selection mechanism; adding a path-selection script shared by two workflow mechanisms is unnecessary here.

Static compilation scales with authored content and included text; there are no additional library hot-path allocations or calls. No runtime performance benchmark is needed for a documentation layout change. Retain current benchmark provenance and raw-report handling rather than regenerating results for editorial work.

Hosted guide routes in README and the example catalogue can return 404 until the revision is published. The maintainer accepts this pre-publication Lychee limitation: its configuration excludes remote checks for the six public section prefixes. The strict site build checks local pages, anchors, snippets, and assets, and preview inspection covers direct entry links. Other external URLs, the homepage, and legacy hosted guide URLs retain their existing network checks. This does not verify the deployed revision; inspect it after ordinary publication. No custom validator or hook wrapper is added.

## Risks / Trade-offs

- [Moving a mixed guide loses an operating caveat] → Use the content map and compare source/destination sections before removing the original; retain security and freshness limits prominently.
- [Inclusion works in the browser but repository Markdown shows directives] → Put an explicit canonical-source link in each wrapper and keep canonical prose readable; do not maintain duplicate fallback content.
- [Framework documentation describes a newer release than the lock] → Check required feature support in the locked release and make any narrow docs-only update before relying on it.
- [The stock 0.0.67 theme has a documented 404 skip-link defect] → Preserve the maintainer note and [upstream tracking issue](https://github.com/zensical/zensical/issues/997). Recheck the generated 404 page after any framework update; report a remaining defect without treating it as a regression introduced by the content restructure.
- [Source inclusion creates additional publishing inputs] → Select example instructions and code in both PR validation and publication filters, and verify a source edit appears in the built site.
- [Old anchors break after a split] → Map all existing public headings and inspect redirect destinations under `/client-query-cache/`.
- [Active examples work changes the delivered catalogue] → Reconcile delivered filenames at apply time; keep adapter development in its existing change.
- [Published deployment differs from checkout] → The web tool could not retrieve the current hosted homepage during planning. Verify the locally built journey first and inspect the hosted result after ordinary publication; do not treat checkout inspection as live-site verification.

## Migration Plan

Create a recoverable checkpoint before bulk content moves. Move and split content according to the map, then wire inclusion, navigation, redirects, and all affected repository references. Update CONTRIBUTING's authoring rules to distinguish site-local guidance from explicit source/evidence links and document the public/development boundary. Add one concise changelog entry describing the final navigation and organization.

Before ordinary publication, inspect the clean site under the project subpath: installation → both tutorials → usage → benchmarks → every delivered integration → reference → operations. Check search, keyboard/mobile navigation, both appearances, code copying, legacy headings, and absence of development material in output/search. Use the existing strict build and Lychee mechanisms for authored-link validation; do not add a custom website validator.

Once applied and reviewed, the existing main-branch Pages workflow publishes the built revision. Rollback is a repository revert of the content/configuration/filter changes followed by the established publication process; no external hosting configuration change is required.
