# Proposal

## Why

A failed stream startup currently produces another initialization attempt and warning on every eligible read. Starting a stream also holds the coordinator lock across network I/O, delaying unrelated databases.

## What Changes

- Bound initial startup retries and coordinate activation independently per database.
- Preserve the existing health and bypass interfaces while documenting the new startup timeline.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `change-stream-coherency`: startup retry, concurrent activation, and shutdown ownership.

## Impact

Both stream coordinators and manager eligibility paths, shared stream policy, their lifecycle tests, deployment and monitoring guidance, and affected Context7 rules. No new dependency or public configuration argument.
