# Design

## Context

The public guides are in `docs/user`; internal documentation is in `docs/development`. The example pages contain Pymdown directives that include canonical programs and the catalogue during the site build. Cached synchronous and asyncio `find` and `aggregate` currently return materialized lists.

## Decisions

### Maintain a small root configuration

Use `$schema`, `folders`, `excludeFolders`, `excludeFiles`, and `rules` in root `context7.json`. The [owner documentation](https://context7.com/docs/library-owners) documents these settings. The [official schema](https://context7.com/schema/context7.json) has no mandatory top-level fields, allows up to 50 rules of 1–255 characters, and rejects unknown fields. `url` and `public_key` are paired ownership fields; ownership setup is outside this change, so omit them here. This omission is a scope choice rather than a permanent requirement.

Keep rules hand-maintained and compare their meaning with the implemented API and canonical guides. JSON validation cannot establish semantic agreement. Summarize client/manager imports, cached read boundaries, list returns, raw operations, asynchronous invalidation, eligibility, lifecycle, coherence versus eviction, and deployment prerequisites. The active cursor proposal is not implemented behavior; its eventual implementation must update affected rules.

### Index public guides directly and exclude snippet wrappers

Use `folders: ["docs/user"]` and `excludeFolders: ["docs/user/examples"]`. Context7 documents that exclusions take precedence over inclusions and that root Markdown remains eligible regardless of `folders`. Explicitly exclude root maintainer filenames and retain Context7's default excluded filenames in `excludeFiles`; the root README remains eligible.

The [indexing documentation](https://context7.com/docs/adding-libraries) does not promise Pymdown snippet expansion and does not index raw Python when documentation exists. Excluding the wrapper directory avoids relying on expansion. Other public guides contain authored usage examples and API guidance. Complete integration programs and their catalogue remain in canonical source files and the existing hosted documentation site; this change does not require them in Context7.

No rendered branch, additional publication job, source registration, or custom generator is needed. This keeps the change focused on repository-maintained usage rules.

### Use existing maintenance and validation

Update `AGENTS.md` and `CONTRIBUTING.md` to require same-change updates to affected rules and guides. Use existing JSON/prose checks and an established validator against the official schema. Check inclusion/exclusion settings against Context7's documented semantics and review rules against current code and public documentation. Do not add configuration-mirroring tests or make completion depend on remote indexing after merge.

## Trade-offs

Context7 will omit the integration wrapper pages and full programs. The hosted documentation continues to provide them through its existing rendering workflow. Manual rules can drift, so semantic review remains part of API documentation review.

## Migration

Context7 can consume the root configuration through its existing Git library when the change is available. No service setup or publication surface is added. Reverting the file and maintenance instructions reverses the change.
