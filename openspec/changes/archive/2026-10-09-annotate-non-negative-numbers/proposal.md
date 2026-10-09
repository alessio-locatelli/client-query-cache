# Proposal

## Why

The type-annotations convention converts only ranges that existing prose stated. Most counters, sizes, indexes, generations, durations, and timestamps still use a bare `int` or `float` even though they can never be negative, so readers and tools see a wider domain than the code allows.

## What Changes

- Every written `int` or `float` for a value that cannot be negative becomes `NonNegativeInt` or `NonNegativeFloat`, or a narrower alias such as `PositiveInt` or `PositiveFloat` where the range is known, in `src/`, `tests/`, and `benchmarks/`.
- Add the `NonNegativeFloat` alias.
- Values that can legitimately be negative keep a bare `int` or `float`.
- The `AGENTS.md` annotation guidance states the rule.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `type-annotations`: numbers that cannot be negative state their range.

## Impact

Static annotations change across library, test, and benchmark code. Runtime behavior, validation, and the static types callers see are unchanged.
