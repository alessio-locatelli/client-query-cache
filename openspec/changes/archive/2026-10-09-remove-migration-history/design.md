# Design

## Context

See [proposal.md](proposal.md) for scope.

## Decisions

### Committed evidence keeps its recorded package name

`reports/stream-cost/v1/decision-evidence.report.v1.json` records the installed package versions at measurement time. Rewriting that entry would falsify the evidence, so it stays as recorded.

### Removing the capability retires its specification

When every requirement of `prototype-recovery` is removed, a kept main specification would have no requirements and fail validation. The change sets `retire_capabilities` so that archiving deletes the specification.

No research is needed.
