# Proposal

## Why

The repository has no matched evidence showing whether uvloop improves its asynchronous workloads or reduces test execution time. An evaluation can identify useful development optimizations and support accurate application guidance.

## What Changes

- Evaluate event-loop choice through the existing measurement and test infrastructure, with adoption conditional on the delta specifications.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `shared-cache-benchmarking`: Matched event-loop comparisons and evidence-based application guidance.
- `test-environment`: Independent test-duration evaluation and selective event-loop coverage.

## Impact

Potential implementation surfaces are `benchmarks/public_shared_cache.py`, its harness tests, `tests/conftest.py`, selected asynchronous tests, `pyproject.toml`, `uv.lock`, and `docs/user/getting-started/asyncio.md`. Contributor instructions and existing Context7 rules may need alignment with adopted behavior. No production package or Rust changes are planned.
