## Why

`pragma: lax no cover` currently suppresses coverage for retry, timeout, and
test-double paths without a consistent proof that they are realistic. This can
hide flaky behavior and turn a broken test harness into a silent timeout.

## What Changes

- Audit every `pragma: lax no cover` outside the MongoDB specifications submodule.
- Retain only exclusions backed by a minimal reproduction and repeated-run
  evidence that the real condition occurs intermittently.
- Replace unsupported speculative paths with an assertion, an ordinary
  reasoned `pragma: no cover`, or deletion, according to their actual contract.
- Remove the coverage configuration support for `lax no cover` if no supported
  occurrences remain.

## Capabilities

No specification delta: this changes internal test-harness and test-double
policy only, with no library API or runtime behavior change.

## Impact

- Affected files: test fixtures, stream test helpers, and coverage configuration.
- No public API, production dependency, or runtime cache behavior changes.
