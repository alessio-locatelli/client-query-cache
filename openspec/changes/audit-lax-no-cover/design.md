## Context

See [proposal.md](proposal.md). The audit covers eleven exclusions in shared
fixtures and stream tests. They fall into three mechanically different groups:
container readiness retries, test timeout guards, and deliberately unreachable
test-double or concurrent-worker paths.

## Goals / Non-Goals

**Goals:**

- Make every remaining coverage exclusion state a concrete, verified reason.
- Make test helpers fail with useful evidence instead of silently absorbing
  unexpected failures.
- Keep normal stream and integration behavior unchanged.

**Non-Goals:**

- Add retry behavior to production cache code.
- Treat timing sleeps as proof of a race.
- Change MongoDB, Testcontainers, or pytest logging policy outside the audited
  exclusions.

## Decisions

- Classify each occurrence by direct execution semantics, not its comment or
  coverage status. Keep `lax no cover` only when a minimal reproduction plus
  repeated runs demonstrate that the real timing-dependent route occurs
  intermittently. Injecting a synthetic exception is not sufficient evidence.
- Replace expected-but-unreachable helper paths with ordinary `no cover`
  reasons, or assertions where reaching the path means the test double has
  violated its contract. Remove silent exception swallowing where it masks a
  failed worker.
- Remove the coverage configuration's `lax no cover` pattern only after all
  occurrences are eliminated. Keeping the pattern would allow future unproven
  exclusions without review.

### Audit inventory

| Location                                            | Current path                 | Required disposition evidence                                   |
| --------------------------------------------------- | ---------------------------- | --------------------------------------------------------------- |
| `tests/conftest.py` (removed)                       | MongoDB ping retry           | No MRE supported retention; remove the unproven retry           |
| `tests/conftest.py:64`                              | Docker client construction   | Verify a missing runtime reports the documented diagnostic      |
| `tests/asynchronous/test_streams.py:61`             | closed scripted stream       | Direct test, assertion, or deletion                             |
| `tests/asynchronous/test_streams.py:197`            | polling timeout              | Reasoned ordinary exclusion or direct failure-path test         |
| `tests/asynchronous/test_streams.py:843`            | cancelled server-info return | Assertion or deletion                                           |
| `tests/asynchronous/test_streams.py:870`            | cancelled stream's `next`    | Assertion or deletion                                           |
| `tests/asynchronous/test_streams_integration.py:60` | polling timeout              | Reasoned ordinary exclusion or direct failure-path test         |
| `tests/synchronous/test_streams.py:190`             | polling timeout              | Reasoned ordinary exclusion or direct failure-path test         |
| `tests/synchronous/test_streams.py:311`             | raced start exception        | MRE plus repeated intermittent evidence, or non-lax replacement |
| `tests/synchronous/test_streams.py:313`             | unexpected start exception   | Reasoned ordinary exclusion or explicit assertion               |
| `tests/synchronous/test_streams.py:319`             | unexpected stop exception    | Reasoned ordinary exclusion or explicit assertion               |
| `tests/synchronous/test_streams_integration.py:58`  | polling timeout              | Reasoned ordinary exclusion or direct failure-path test         |
| `.coveragerc:8`                                     | exclusion pattern            | Remove after all source occurrences are gone                    |

Alternatives considered: retaining the existing exclusions based on historical
coverage comments would preserve 100% coverage, but would not distinguish real
flakiness from speculative guards. Replacing all paths with timing-based tests
would itself create flaky tests.

## Risks / Trade-offs

- A previously hidden asynchronous failure may now fail a test immediately →
  this is intended; error propagation supplies the diagnostic that retries
  removed.
- Removing a legitimate flaky retry could expose a real infrastructure race →
  retain it only with a minimal reproduction and repeated-run evidence of
  intermittent behavior.
- Test coverage can drop while exclusions are removed → add a direct test,
  reasoned ordinary exclusion, assertion, or deletion in the same edit.
