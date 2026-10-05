## Context

See [proposal.md](proposal.md) for motivation. The existing README requirement asks for detailed-guide links; the archived checklist is not the active specification.

## Goals / Non-Goals

Keep durable README boundaries in the existing documentation capability. This change adds no documentation tooling or runtime behavior.

## Decisions

- Amend the existing README requirement and add focused rules for evidence, a minimal example, and redundant platform guidance. Promoting the entire archived checklist would make active guidance longer and retain its superseded project-name heading advice. The concise specification captures the current contract instead.
- Use one synchronous example with client and manager context managers and two identical reads. It shows the public API and cleanup without writes, options, or a second asyncio sample. A full tutorial would offer more context but duplicate the hosted quick starts.
- Keep the production-readiness paragraph, prerequisites, and consistency caveat. Replace the guide catalogue with direct quick-start, benchmark, and integration-example references so readers can investigate benefits and usage without duplicating site navigation.

These choices require no prototype or further research; the public quick starts already demonstrate the API and lifecycle.

## Risks / Trade-offs

- A repeated read can miss during startup or concurrent writes; sample comments describe possible reuse rather than promise a hit.
- A tiny example does not cover deployment setup or asyncio; the quick-start guide links to the relevant guidance.
