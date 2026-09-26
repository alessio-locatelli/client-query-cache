# Design

## Context

See [proposal.md](proposal.md) for the naming decision. Today the repository and README use `mongodb-client-cache`, the distribution and lockfile use `mongo-client-cache`, and the source and public imports use `mongo_client_cache`. The current `uv_build` configuration derives the package from `src/`. The installed-package test and CI import check exercise the old path. Existing benchmark reports and archived OpenSpec changes record past evidence under the old identity.

## Goals / Non-Goals

**Goals:** Make a clean install expose one consistent new distribution and import package; make current project guidance and automation use the new identity; preserve interpretable historical evidence.

**Non-Goals:** Change caching behavior, PyMongo support, or benchmark results. Provide a second, permanent import namespace.

## Decisions

- Rename `src/mongo_client_cache` to `src/client_query_cache` and update imports throughout project-owned source, tests, benchmarks, packaging, CI, and examples. Keep existing public class and method names. A compatibility alias would retain the name being retired, create two supported entry points, and complicate packaging; this is an explicit breaking rename instead.
- Check whether PyPI permits claiming `client-query-cache` before changing distribution metadata; if unavailable, stop and resolve the public name rather than ship a split identity. Change the distribution metadata and regenerate `uv.lock` together. Verify the built sdist and wheel in isolated environments, including sync and asyncio imports, because source-tree imports alone would miss packaging mistakes. Coordinate the installed-package check with the active `add-release-verification` change rather than duplicating its release workflow.
- Update current README, migration guidance, contributor setup, container labels/names, repository links, and user-visible errors that identify the library. The `document-public-library` change remains responsible for broader public documentation; this change supplies its canonical name and import examples.
- Preserve archived OpenSpec records and retained benchmark reports as historical evidence. Keep existing versioned report identifiers stable so old reports remain recognizable. If new decision-evidence output changes the `versions.mongo_client_cache` field, version that output format and keep the retained v1 file unchanged. The stream-cost report's v1 `$id` is a format identifier, not a current project link; do not alter it merely to remove an old word.
- Prepare the repository content under the new name, then rename the GitHub repository and update the local remote and current links. GitHub redirects the old repository address, but links and integrations should use the canonical address. The repository rename requires administrator access and is distinct from local code edits.

## Risks / Trade-offs

- [Downstream imports fail after upgrade] → Mark the rename as breaking and give exact dependency and import substitutions in migration guidance.
- [A source import passes while the wheel is broken] → Exercise sdist and wheel imports from outside the checkout.
- [A broad replacement rewrites historical data or external submodule content] → Scope replacements to project-owned, current files and review versioned evidence separately.
- [A target public name is unavailable or external integrations retain the old URL] → Check the PyPI distribution and GitHub repository names before either public rename; verify the canonical URL and update consumers after the repository rename.

## Migration Plan

1. Confirm the distribution and repository names can be claimed, then create a reversible checkpoint before the broad source/import rename. Update the package, metadata, lockfile, current automation, diagnostics, tests, and current documentation; retain historical artifacts as described above.
2. Validate locked installation, built distributions, public imports, and representative behavior. Review any current workflows or external references that depend on the repository URL.
3. Rename the GitHub repository when the new content is ready, then update the local remote and verify the canonical URL and redirect. If that external step cannot be completed, report the split identity as a blocker rather than claim the rename is complete.
4. Communicate the breaking dependency and import substitutions. Rollback, if needed, restores the former repository and package names from the checkpoint and informs downstream users of the reversal; a repository URL redirect alone does not restore the old Python imports.
