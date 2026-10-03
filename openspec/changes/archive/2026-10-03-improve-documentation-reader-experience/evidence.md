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

The event guard accepts main pushes/manual dispatch and successful `Publish to PyPI` completion; failed/cancelled completions and non-main manual dispatch cannot build/deploy. The controller always checks out main, queries current `/releases/latest`, rejects draft/prerelease identities and explicitly fetches the release tag and any recorded retained correction ref, then verifies the pinned correction SHA is reachable. It reads no triggering-run code/artifact, so delayed older release completion still resolves current stable. PR assembly uses the committed validation tag, with no mutable release lookup. Contents remains read-only; only deployment receives Pages/OIDC permissions. The scoped Zizmor trigger exception records this trust boundary.

Publication was not performed. Live Pages selection, redirects and source links require inspection after ordinary publication; Lychee's documented unpublished-route exclusions retain that accepted boundary. The validator also reports pre-existing long-requirement informational notices in unrelated specs; this change and its documentation spec validate without those notices. The existing Zensical 404 skip-link limitation remains recorded in CONTRIBUTING.

## Review corrections

The external review identified destructive replacement after a failed final rename and raw-SHA retrieval of a correction outside rebased main history. Both findings were accepted. Artifact staging now copies beside the output, keeps the backup outside automatic cleanup, restores it on installation failure and preserves it if restoration fails. Parametrized OS-error injections cover backup, installation and restoration with `EXDEV` and access errors, plus failed first installation. All final rename endpoints are on the destination filesystem.

The correction record now uses `refs/pull/143/head` for retrieval while retaining its exact SHA as content identity. Both workflows fetch this supported ref; source selection rejects unsupported branch refs and unreachable commits. A bare-remote fixture rewrites main commit identity, deletes the original branch and clones afresh, then recovers the exact correction through the retained PR ref. Dedicated documentation-tag retrieval is also covered. GitHub documents retained inactive PR refs; a pre-merge force-rebase removing the pinned commit requires a reviewed record update rather than an automatic fallback.

The updated targeted run completed 78 cases. Combining it with real CLI assembly exercised every orchestrator line and branch. Edited test files were inspected in full. Warm combined builds took 1.92 seconds before and 1.88 seconds after; these single samples show no material build-time increase, not a speedup claim. The final artifact contains 97 files and 3,242,553 bytes; replacement alone had a 0.0060-second median across 20 local runs. Reproduce total timing with `/usr/bin/time just docs-build-editions v0.2.0`; measure replacement by calling `replace_artifact(Path("site").resolve(), temporary_output)` repeatedly under `TemporaryDirectory` and timing with `perf_counter`. Staging adds one artifact-sized copy during replacement; runtime/cache paths are unchanged. Raw diagnostics remain untracked.

## Checkout permissions and publication scope

Fresh and replacement assembly regressions reproduced `PermissionError` when the checkout parent had its write bits removed, despite writable checkout and separately configured `TMPDIR`. Removing the explicit parent workspace location made both cases pass under the normal unprivileged account. The fixture restores directory permissions and the temporary-storage configuration during teardown. The regression also records actual build-command working directories and asserts that the initial build workspace is in the configured temporary storage, making placement verification independent of process privileges.

The targeted orchestration and CI-selection run completed 80 cases, including both restricted-parent builds without skips. Combined with actual command assembly, orchestrator line and branch coverage remains 100%. The instrumented combined build completed in 2.05 seconds with warm dependencies; reproduce with `/usr/bin/time uv run --all-groups -- coverage run --rcfile=/dev/null --branch --source=scripts.build_versioned_docs -m scripts.build_versioned_docs v0.2.0`. This storage-location change adds no rendering steps or runtime work.

The publication push filter excludes `.github/workflows/test.yml`; the existing CI-selection case still selects documentation validation for that path. Workflow changes that only affect PR validation therefore exercise CI without independently triggering Pages publication. No custom workflow validator or release-note entry was added for these contributor-tooling corrections.

CI also measures fixture source. The precautionary permission-bypass skip was unexercised and failed that coverage gate; removing it follows the project's rule against speculative test defenses. The same 80 cases passed, and the complete edited test file now has 243 statements and 20 branches with no missing lines or branches under the repository's coverage configuration. `strict-no-cover` reports no wrongly excluded lines. No new helper tests or coverage exclusions were added.
