# Implementation evidence

## Native exports

`just docs-build` selects all 16 current public pages in seven populated sections.
Every indexed canonical URL resolves to a local Markdown file, including
`reference/api/index.md`. Home, API, operations, benchmarks, the example catalogue,
and all three integrations retain readable headings, links, code, and tables where
present. The three exported programs contain their complete canonical Python
sources; snippet directives and theme controls are absent.

`wc -c -w site/llms-full.txt` reports 89,023 bytes and 9,949 words. This is below the
design's 1 MiB review trigger and contains useful public guidance without navigation
or theme repetition, so combined output remains enabled.

A baseline captured with `just docs-build` before configuration edits was compared
with the new build. All HTML article bodies match after removing the added native
copy button. Generated files remain ignored under `site/`; baseline and raw
inspection output are outside the checkout.

## Assembly boundary

The real-build tests exercise stable sources without export configuration, separate
development content, canonical edition destinations, byte-identical stable/root
discovery files, default and nested combined paths, disabled combined output, and
missing exports preserving the previous complete artifact. Setup and fault injection
remain in fixtures; repeated build cases use parametrization.

The existing **Documentation build** job still invokes `just docs-build-editions`;
`scripts/ci_scope.py` selects both `zensical.toml` and the assembler. No workflow or
validator was added. Zensical 0.0.67 validates `full_output` before the edition
builds can succeed: absolute paths and traversal components are rejected by its
native configuration normalization. Root staging runs only after those builds;
there is no second path validator in the assembler.

## Outstanding acceptance

The browser connector had no available browsers. The user authorized headless
Playwright through host Podman from Toolbx. In the `just docs-serve` preview,
Celery's Copy as Markdown copies exactly its emitted Markdown (4,885 UTF-8 bytes).
Search, appearance controls, and edition selection acceptance are still pending. The documented stock
[404 limitation](../../../docs/development/ci-validation-caches.md#documentation-validation-limitations)
is unchanged.

A disposable corpus used the same seven section mappings and normal clean strict
Zensical builds. An included snippet changed from one revision to another, and a
nested Usage page was added, renamed, then removed. The index, per-page Markdown,
combined output, and HTML followed each revision; renamed and removed output paths
disappeared. No generated export was edited.

The full versioned corpus and final documentation CI acceptance are still pending. The change remains active until all
required acceptance tasks are complete.
