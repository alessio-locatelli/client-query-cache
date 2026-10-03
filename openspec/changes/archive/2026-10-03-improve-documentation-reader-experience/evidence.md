# Implementation evidence

## Versioning compatibility

The locked mike fork and Zensical 0.0.67 built two TOML-configured editions in a disposable Git repository. Headless Chromium verified the stable default, exactly two edition titles, shared-page/fragment switching, missing-page fallback, subpath URLs and distinct search content. A missing heading returned exit 1 through mike with `project.strict = true`; no extra prebuild is needed.

## Reader journey and local MongoDB

The working-tree preview verified installation → synchronous → asyncio footer navigation. Public prose no longer contains the duplicated installation introduction, generic continuation endings, installation reminders or “effective caching”. The README badge matches `requires-python = ">=3.14.6"`.

The original Compose helper failed on repeated startup with “already initialized”. The corrected helper checks replica-set status, initializes only an uninitialized deployment and waits for a writable primary. Fresh and repeated documented startup sequences succeeded through the host Podman Compose provider (Docker CLI is unavailable in this toolbx). The disposable `cqc-docs-local` fixture was stopped afterward. No live database was used.

## Stable provenance

The reviewed correction commit is `f9355d6043d35ff9d17f6cb76b7e8a8e09e32f14`; release `v0.2.0` resolves to `c0104cb43e46354a245b56ca1bc9377635352903`. The builder accepted their identical runtime tree, executable examples and runtime `[project]` metadata. These are public Git identities.

Root redirects are rendered through Zensical using the stable source corpus as existing targets. That extra rendering supplies framework target validation; its stable output is discarded so the mike edition remains authoritative. No HTML rewriting or custom validator is used.

## Combined artifact and regression coverage

`just docs-build-editions v0.2.0` completed in 1.92 seconds with warm dependencies; `du -sh site` reported 3.4 MiB. Reproduce with `/usr/bin/time just docs-build-editions v0.2.0` and `du -sh site`. No runtime code or executable examples changed, so this has no cache hot-path profiling cost. Raw build/browser/coverage diagnostics remain untracked.

The public-behavior tests use disposable Git repositories for exact tag selection, bounded immutable backports, runtime/example/project mismatch rejection, independent development snapshots, invalid release identity, failed renderer/missing-layout propagation, first/replacement artifact builds and linked-output rejection. The targeted run completed 66 cases across both edited test files. Combining their branch coverage with a real CLI assembly exercised every line and branch of the new orchestrator. Both test files were inspected in full; shared fixture setup and parametrization replace repeated scenario setup. Framework rendering/selection is inspected through actual builds and Chromium, rather than a custom configuration validator.

## Browser inspection

Headless Chromium inspected all 16 pages in each edition, nine README/catalogue entry links and 38 legacy URLs (three base routes plus 35 captured headings). It verified stable default, exactly two labels, desktop and mobile navigation, both appearances, code copying, keyboard search for `max_await_time_ms`, keyboard same-page/fragment edition switching, installation → synchronous → asyncio footer navigation and edition-local catalogue/search/source links. A disposable development-only page fell back to the stable homepage when switching, and neither its page nor its distinct search tokens appeared in stable. Internal development/research material remains outside both edition corpora. The documented static server at the artifact root also handled default/direct redirects and edition switching.

## Workflow and publication boundary

The event guard accepts main pushes/manual dispatch and successful `Publish to PyPI` completion; failed/cancelled completions and non-main manual dispatch cannot build/deploy. The controller always checks out main, queries current `/releases/latest`, rejects draft/prerelease identities and explicitly fetches the tag and any immutable backport SHA. It reads no triggering-run code/artifact, so delayed older release completion still resolves current stable. PR assembly uses the committed validation tag, with no mutable release lookup. Contents remains read-only; only deployment receives Pages/OIDC permissions. The scoped Zizmor trigger exception records this trust boundary.

Publication was not performed. Live Pages selection, redirects and source links require inspection after ordinary publication; Lychee's documented unpublished-route exclusions retain that accepted boundary. The validator also reports pre-existing long-requirement informational notices in unrelated specs; this change and its documentation spec validate without those notices. The existing Zensical 404 skip-link limitation remains recorded in CONTRIBUTING.
