# Design

## Context

See [proposal.md](proposal.md) for motivation and the [documentation delta](specs/public-library-documentation/spec.md) for acceptance criteria.

`zensical.toml` renders `docs/user` into ignored `site/`; its 16 Markdown pages cover the requested sections. Example pages expand `examples/README.md` and Python programs through `pymdownx.snippets`. The public sources and these included files total approximately 89 KB before rendering. `uv.lock` already contains Zensical 0.0.67, so no dependency change is needed.

`just docs-build` runs a locked clean strict build. CI and Pages use `just docs-build-editions`, whose existing `scripts/build_versioned_docs.py` extracts independent stable and development snapshots, invokes Zensical through mike, and assembles one artifact. Root HTML routes lead to stable guidance. The recorded stable correction's configuration lacks `llmstxt`, and the root redirect build only configures redirects. Adding the plugin to the current configuration alone would therefore miss stable exports and root discovery files.

Upstream evidence:

- [Zensical native plugin support](https://zensical.org/docs/compatibility/mkdocs/plugins/#llmstxt) documents section selection, default cleanup, optional combined output, canonical URL fallback, and Copy as Markdown.
- [Pinned configuration normalization](https://github.com/zensical/zensical/blob/v0.0.67/python/zensical/config.py) uses `fnmatch` patterns and applies mike's edition to `site_url` before rendering.
- [Pinned export implementation](https://github.com/zensical/zensical/blob/v0.0.67/crates/zensical/src/compat/mkdocs/plugin/llmstxt.rs) derives Markdown paths from published HTML routes and converts selected rendered pages.
- [Upstream integration tests](https://github.com/zensical/zensical/blob/v0.0.67/python/tests/integration/test_llmstxt.py) cover TOML, directory URLs, nested matching, cleanup, missing explicit pages, and regeneration. These are framework behaviors, not reasons to duplicate tests here.

## Goals / Non-Goals

**Goals:** Keep generation entirely inside Zensical while making its outputs available through the existing edition assembler. Keep export selection maintainable as public sections grow and distinguish source-checkout outputs from mike's disposable artifact repository.

**Non-Goals:** Redesign edition publication, replace stable source selection, or implement conversion, index serialization, URL rewriting of generated exports, or a second validation framework. Other scope exclusions are in the proposal.

## Decisions

### 1. Configure native exports with section-relative globs

Add this configuration to `zensical.toml`:

```toml
[project.plugins.llmstxt]
markdown_description = "Public guidance for synchronous and asyncio PyMongo applications. Writes use PyMongo directly; change-stream invalidation is asynchronous."
full_output = "llms-full.txt"

[project.plugins.llmstxt.sections]
"Home / overview" = ["index.md"]
"Getting started" = ["getting-started/*.md"]
"Usage" = ["usage/*.md"]
"Examples" = ["examples/*.md"]
"API reference" = ["reference/*.md"]
"Operations" = ["operations/*.md"]
"Benchmarks" = ["benchmarks/*.md"]
```

These paths are relative to `docs_dir`, not the repository root. Zensical's `fnmatch` behavior lets `section/*.md` include both direct and nested pages; `section/**/*.md` would omit direct pages. An explicit Home entry and one glob per section avoid duplicates and manual page inventories. A whole-tree glob would lose useful grouping and explicit scope.

Leave `base_url`, `autoclean`, and preprocessing unset. The description adds usage boundaries beyond `site_description` without replacing canonical guidance. Append `content.action.copy` to the existing feature list. Default directory URLs mean a page such as `reference/api.md` exports at `reference/api/index.md`; inspect emitted links rather than assuming source paths equal output paths.

### 2. Preserve each edition’s export policy with a bootstrap fallback

Use each snapshot's own `project.plugins.llmstxt` table when present. Only a stable snapshot that lacks the table inherits the selected development policy, allowing the bootstrap stable correction to export its own corpus. Append `content.action.copy` while preserving each snapshot's other theme features, navigation, Markdown extensions, metadata, guides, and snippets. Root discovery files and the combined-output filename follow the effective stable policy.

The current plugin table has only a universally applicable description, globs, and `index.md`; it does not identify unreleased APIs or require new development-only pages. Development policy changes must remain compatible with stable corpora that still need the bootstrap fallback. Once a release carries its own table, later development changes to section paths, ordering, descriptions, or combined output cannot alter that release’s export policy. Source selection and its runtime/example/metadata comparisons remain intact.

Allow mike and Zensical to compute edition-aware `site_url`; do not add `base_url` or manually append edition prefixes. Verify final `/stable/` and `/dev/` URLs in the assembled indexes. An alternative of changing only the current snapshot would leave the existing stable configuration without exports. Updating the immutable stable correction for every rendering feature would couple publication policy to content provenance unnecessarily.

### 3. Reuse stable native outputs at the documentation root

After both editions and root HTML redirects have been staged, copy the stable edition's Zensical-generated `llms.txt` and enabled `llms-full.txt` byte-for-byte to the artifact root before installing the complete artifact. The copied index links directly to `/stable/` Markdown equivalents; do not copy all Markdown pages into the root or regenerate/rewrite either discovery file. This matches the site's stable default and provides real text at the requested root paths.

Keep `/stable/llms.txt`, `/dev/llms.txt`, both enabled edition combined files, and their per-page Markdown in the assembled artifact. Copying files within the existing assembler is publication integration, not a custom generator or a new Python script. A second root conversion pass would duplicate work, and a root index covering both editions would mix release guidance.

Missing required generated files must fail the assembly visibly through its normal file operations; do not silently publish an incomplete artifact. Handle combined output according to the configured `full_output`, including its disabled state if justified. Preserve complete-artifact replacement and recovery semantics.

### 4. Keep combined output enabled and measure its actual size

The observed source corpus gives no concrete reason to omit combined output. Record generated UTF-8 byte and word counts during implementation and inspect for repetition or unwanted template content. Use 1 MiB as a review trigger, not an automatic cutoff or a new validator: a larger result needs a documented usability assessment before disabling output. Keep the normal default `full_output = "llms-full.txt"` unless measured evidence establishes a problem.

Native conversion adds build-time work proportional to selected rendered content and retains per-page text for aggregation. No request-time or library runtime path changes. This bounded configuration and artifact-copy change follows the generic workflow's lightweight path; record output size and investigate build cost only if validation reveals meaningful overhead. Raw diagnostic output remains untracked.

### 5. Validate outputs at the publication boundary

The normal strict Zensical build owns configuration and missing explicit-page validation. Inspect the complete local and versioned artifacts for section membership, every indexed Markdown target, expanded examples, canonical edition URLs, and combined output. Compare a pre-change HTML build with the new build and exercise Copy as Markdown on a snippet-backed example. Check ordinary navigation, search, and edition selection remain usable.

Extend existing real-build tests in `tests/test_build_versioned_docs.py` only for the new integration responsibilities: an older stable config receives exports, root text is the stable native output, each index resolves to actual files in its edition, and a development-only page does not enter stable output. These catch failures that a successful standalone Zensical build cannot detect. Do not add configuration-parsing tests or duplicate upstream conversion/glob tests. Add no custom validator or separate CI job; existing workflow path selection already covers the configuration and assembler.

`site/` remains ignored in the source repository. Mike already commits rendered files in its disposable local artifact repository as part of normal assembly; that is required tool behavior, not a reason to check generated files into the project's branch.

## Risks / Trade-offs

- [Older stable configuration lacks export settings] → Inherit development’s export policy only when stable lacks a table; preserve any present stable policy, the exact stable corpus, and provenance. Append the copy feature independently.
- [A standalone build passes while root files or edition links are wrong] → Inspect the versioned artifact and cover assembly behavior with existing real-build tests.
- [Default conversion obscures meaningful code or tables] → Inspect API, operations, benchmarks, catalogue, and complete programs. Retain default cleanup unless a concrete generated-content problem warrants revisiting its native setting.
- [Combined output grows] → Record measured size and assess usability before omitting it; avoid a speculative hard limit.
- [Generated HTML differs unexpectedly] → Compare baseline page content and UI, permitting only the native action and its necessary Markdown metadata.
- [Framework 404 skip-link defect] → Preserve the documented [Zensical issue #997](https://github.com/zensical/zensical/issues/997) limitation in `docs/development/ci-validation-caches.md`; this change neither upgrades Zensical nor adds a workaround.

## Migration Plan

Implement the configuration and narrow existing-assembler integration together, then validate both ordinary and edition builds before completion. Add concise contributor instructions for inspecting the index, combined output, and generated page paths. Publication continues through the existing trusted-main workflow after the user requests it; no live service changes occur during planning or local validation.

Rollback consists of reverting the native configuration, assembler integration, and associated contributor guidance, then rebuilding the normal complete artifact. Public HTML sources, release tags, stable correction provenance, and existing bookmarks remain available throughout.
