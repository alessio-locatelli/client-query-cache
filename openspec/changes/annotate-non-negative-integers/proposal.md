# Proposal

## Why

The type-annotations convention converts only ranges that existing prose stated. Most counters, sizes, indexes, and generations still use a bare `int` even though they can never be negative, so readers and tools see a wider domain than the code allows.

## What Changes

- Every written `int` for a value that cannot be negative becomes `NonNegativeInt`, or a narrower alias where the range is already known, in `src/`, `tests/`, and `benchmarks/`.
- Values that can legitimately be negative keep a bare `int`.
- The `AGENTS.md` annotation guidance states the rule.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `type-annotations`: integers that cannot be negative state their range.

## Impact

Static annotations change across library, test, and benchmark code. Runtime behavior, validation, and the static types callers see are unchanged.
