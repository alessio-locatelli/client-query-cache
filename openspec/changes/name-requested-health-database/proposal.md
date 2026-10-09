# Proposal

## Why

`StreamHealthSnapshot.database_name` echoes whatever name the caller passed to `stream_health_snapshot()`, because inspection is local and never checks the name against MongoDB. The field name suggests a validated database, so an empty or mistyped name silently reports `not_started` without that behavior being visible in the API or covered by a test.

## What Changes

- **BREAKING**: Rename `StreamHealthSnapshot.database_name` to `requested_database_name`, without a compatibility alias.
- Specify and test that health inspection echoes the requested name unvalidated, including an empty name.
- Document the field in the monitoring guide, the Context7 rules, and the changelog.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `change-stream-coherency`: health observations identify the requested database name without validating it.

## Impact

The public `StreamHealthSnapshot` dataclass, both managers' health inspection, user documentation, Context7 rules, and the changelog. Callers that read `database_name` must switch to `requested_database_name`.
