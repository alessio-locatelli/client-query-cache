# Proposal

## Why

Coding agents need a structured documentation index and rendered Markdown that includes the site's expanded examples. The project already locks Zensical 0.0.67, whose native `llmstxt` support can produce these resources during ordinary builds without another generator or maintained documentation copy.

## What Changes

- Configure native `llmstxt` in `zensical.toml` with public sections for Home / overview, Getting started, Usage, Examples, API reference, Operations, and Benchmarks. Use paths relative to `docs/user` and section globs that include future pages.
- Generate `llms.txt`, Markdown equivalents of selected pages, and `llms-full.txt` through Zensical. Retain default HTML cleanup and the canonical `site_url`; add a concise description explaining the synchronous/asyncio scope and asynchronous invalidation.
- Add `content.action.copy` to the existing theme features so selected HTML pages expose Copy as Markdown.
- Integrate native exports with the existing stable/development assembly: each edition preserves its own export policy when present, stable sources without one inherit development settings, and documentation-root `llms.txt` and `llms-full.txt` expose stable guidance with links to stable Markdown pages.
- Keep generated files automatic and untracked in the source checkout. Inspect build outputs, snippet expansion, canonical links, combined-document size, and HTML behavior using the normal documentation tooling.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `public-library-documentation`: Add structured agent discovery, rendered Markdown and combined exports, Copy as Markdown, and synchronization with the existing edition-aware build.

## Impact

Implementation primarily changes `zensical.toml`. Small integration edits to `scripts/build_versioned_docs.py` apply the native export settings to older stable snapshots and publish Zensical-generated discovery files at the documentation root; they do not convert content or generate indexes. Existing artifact-level tests may cover this assembly boundary, and `CONTRIBUTING.md` will explain inspecting generated outputs.

No new dependency or documentation generator is needed. The existing documentation CI and Pages workflow already select these inputs and publish `site/`. Runtime APIs, public guide content, source provenance, and the two-edition policy remain intact. Custom search APIs, HTTP content negotiation, crawler detection, analytics, agent-specific 404 handling, and conversion scripts are outside scope.
