# Design

## Context

See [proposal.md](proposal.md) for scope.

## Decisions

### Committed evidence keeps its recorded package name

`reports/stream-cost/v1/decision-evidence.report.v1.json` records the installed package versions at measurement time. Rewriting that entry would falsify the evidence, so it stays as recorded.

### Removing the capability deletes its specification

When every requirement of `prototype-recovery` is removed, the archived main specification would have no requirements. The specification directory is deleted during archiving instead of being kept empty.

No research is needed.
