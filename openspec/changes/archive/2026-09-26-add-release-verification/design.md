## Context

CI proves source-tree behavior, but the old plan also required proof that artifacts can be distributed. That responsibility is deliberately separate from publication.

## Goals / Non-Goals

**Goals:** Verify build artifacts, isolated imports, and version consistency.

**Non-Goals:** This change does not publish to PyPI, create tags, or store publishing credentials.

## Decisions

- Build both sdist and wheel from a clean checkout.
- Install the sdist and wheel into separate isolated environments and import the supported public surfaces from each installation. The validation environment SHALL not use the source checkout as an import fallback.
- Validate version/tag consistency when a tag is supplied, but keep the workflow non-publishing.

## Risks / Trade-offs

- [A tree install hides missing wheel files] → Validate an isolated wheel, not the source checkout.
- [Verification is mistaken for publication] → Name commands and CI jobs explicitly as non-publishing.

## Migration Plan

Add the local command and optional CI job after public API documentation is stable; defer all registry integration to a separate proposal.
