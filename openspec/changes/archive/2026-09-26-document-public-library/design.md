## Context

The current README makes unverified coverage and benchmark claims and documents a proof-of-concept interface. Documentation becomes stable only after the public facade and stream semantics are implemented.

## Goals / Non-Goals

**Goals:** Produce verified public docs and operational guidance from implemented behavior and retained benchmark reports.

**Non-Goals:** This change does not invent an API, configure tooling, or substitute documentation for test evidence.

## Decisions

- Keep developer setup and commands in CONTRIBUTING; keep user installation and behavior in the README and public guides.
- Derive HLD/LLD, capacity formula, lifecycle and error guidance from the implemented manager/facade boundaries.
- Use precise bounded/eventual coherency language and link workload-specific benchmark reports rather than general performance promises.

## Risks / Trade-offs

- [Docs drift from code] → Verify every command and sample in CI-reproducible environments before release.
- [Marketing language overstates consistency] → Name stream recovery and topology limits beside every cache-coherency claim.

## Migration Plan

Remove proof-of-concept claims, write the guides after dependent behavior is complete, test all examples, and link each performance conclusion to a retained report.
