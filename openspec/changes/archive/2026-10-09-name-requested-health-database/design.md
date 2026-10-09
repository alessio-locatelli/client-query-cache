# Design

## Context

See [proposal.md](proposal.md). Health inspection reads an in-process registry and performs no database I/O, so it cannot validate a name without breaking the "Database health inspection is local and read-only" requirement.

## Decisions

### Name the field after what it holds

The field becomes `requested_database_name`, so the attribute itself states that it is the caller's input. Validating the name instead was rejected because MongoDB naming rules differ by deployment, and enforcing them locally would duplicate server policy inside a read-only observation. A deprecated `database_name` alias was rejected because the package is pre-1.0 and no repository code reads the attribute.

No research is needed.
