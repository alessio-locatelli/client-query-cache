# Design

## Context

See [proposal.md](proposal.md) for motivation. GitHub's latest stable release is `v0.3.0`, whose tag includes the public guide layout, native export configuration, and Copy as Markdown feature. The contributor image currently lacks GitHub CLI, although GitHub's Ubuntu runners and this checkout environment provide it.

## Goals / Non-Goals

The existing Python assembler remains responsible for exact committed snapshots. Release discovery belongs to the command surface, and runtime package behavior is outside this change.

## Decisions

### Shared native release discovery

Give `just docs-build-editions` an optional tag argument. Without one, use GitHub CLI's `releases/latest` endpoint and fetch only that named tag from `origin`. An explicit tag retains the existing local-only path. Both workflows call this recipe with read-only step-scoped authentication and `GH_REPO` identifying the base repository, including for fork PRs. Add `gh` to the contributor image's existing Fedora package installation and smoke check.

This keeps GitHub authentication and response filtering in its maintained CLI rather than adding an HTTP client or custom resolver. Duplicating a few discovery commands in the workflows avoids a local CLI requirement, but permits validation and publication to diverge and leaves local builds dependent on manually supplied tags. Selecting the newest local Git tag avoids an API call but cannot distinguish published stable releases from unpublished tags. The [CLI placeholder contract](https://cli.github.com/manual/gh_api) and a live latest-release query establish the selected approach; no further research or follow-up is necessary.

### Release snapshots own their documentation

Remove correction-source selection, its runtime comparisons, and edition export-policy inheritance. Preserve each snapshot's native export policy and Copy as Markdown configuration rather than patching older snapshots to add features. A missing guide layout or required export table fails before final artifact replacement.

Keeping the old paths would support obsolete releases at the cost of retaining configuration and tests for an unused publication path. Releasing prose corrections independently of package releases is intentionally no longer supported. The observed release contents resolve compatibility questions; no further research or follow-up is necessary.

### Changelog guidance

This change affects documentation infrastructure without changing the PyPI package's behavior, so it intentionally has no package changelog entry. The user also explicitly requested a hidden editing hint in `CHANGELOG.md`. That comment is the source of truth for changelog editing policy; `CONTRIBUTING.md` and `AGENTS.md` reference it. This decision introduces no repository-wide rule against duplication.

## Risks / Trade-offs

- Automatic builds depend on GitHub availability and CLI authentication. Required discovery and fetch failures propagate; explicit local-tag reproduction remains available.
- The latest release can change between PR validation and publication. Each invocation resolves one release and logs its exact source commit; this change does not introduce a permanent release pin.
- Older tags without the guide layout or native exports cannot use the combined builder. Ordinary single-corpus preview and strict builds retain their existing command surface.
- Rollback is a repository revert. No package tags or deployed services are mutated during implementation.
