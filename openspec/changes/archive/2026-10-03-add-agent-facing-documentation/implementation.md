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

## Release export policy independence

`just pytest tests/test_build_versioned_docs.py -q` covers a released tag with its
own export policy and a development snapshot that renames `usage/` to `learning/`.
The four combinations of enabled/disabled stable and development combined output
failed before the correction: stable adopted the development description and lost
its Usage page. After the correction, the real assembled artifacts preserve each
edition’s description, section names/order, selected Markdown, and combined-output
setting. Root text equals stable output, including a nested stable combined path;
development-only combined output is absent at the root. The full test/coverage run
reports 100% with the configured strict-no-cover checks, and the documented
`just docs-build-editions v0.2.0` build succeeds. Existing real-build cases
continue to cover stable sources without a table and missing-export recovery.

## Acceptance

The browser connector had no available browsers. The user authorized headless
Playwright through host Podman from Toolbx. In the `just docs-serve` preview,
Celery's Copy as Markdown copies exactly its emitted Markdown (4,885 UTF-8 bytes).
Search finds Celery guidance, dark/light appearance toggles work, and sidebar
navigation opens API guidance. In the versioned artifact, root HTML opens stable guidance; the selector switches
Celery to development and back while retaining its page path. Both editions'
clipboard contents equal their emitted Markdown. No browser JavaScript errors
occurred. The documented stock
[404 limitation](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/ci-validation-caches.md#documentation-validation-limitations)
is unchanged.

A disposable corpus used the same seven section mappings and normal clean strict
Zensical builds. An included snippet changed from one revision to another, and a
nested Usage page was added, renamed, then removed. The index, per-page Markdown,
combined output, and HTML followed each revision; renamed and removed output paths
disappeared. No generated export was edited.

`just docs-build-editions v0.2.0` builds the recorded stable correction and the
committed development snapshot. Each edition indexes 16 generated Markdown pages;
all 32 destinations resolve locally. The combined stable corpus is 90,481 bytes and
9,949 words; development is 89,351 bytes and 9,949 words. All 82 canonical internal
links in each combined corpus resolve locally within their own edition. Root
`llms.txt` and `llms-full.txt` equal stable outputs byte-for-byte. The recorded
source identities, stable pinned GitHub source links, and independent development
links are preserved.

The user accepted local execution of the existing **Documentation build** command
in place of a hosted CI run. `just docs-build-editions v0.2.0` succeeded with the
explicit recorded validation tag and retained correction ref. No hosted CI run is
claimed.
