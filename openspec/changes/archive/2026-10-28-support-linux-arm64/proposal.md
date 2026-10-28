# Proposal

## Why

[Issue #340](https://github.com/alessio-locatelli/client-query-cache/issues/340)
asks for an evidence-backed first portability target. The
[feasibility report](../../../../reports/platform-portability/feasibility.md)
identifies Linux ARM64 as the smallest extension of the current deployment model.

## What Changes

- Add Linux ARM64/glibc support qualified by native runtime evidence.
- Extend release distribution and native acceptance to the proposed target.
- Keep other operating systems and libc implementations outside implementation.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `shared-worker-cache`: Extend the distribution requirement to the new target.
- `release-verification`: Verify each supported architecture on matching hardware.
- `continuous-integration`: Add focused native ARM acceptance without multiplying
  the existing Python compatibility matrix.

## Impact

The implementation affects the shared server platform guard and its tests,
release build/verification/publication orchestration, targeted CI execution,
installation guidance and Context7 rules. Public cache APIs and the shared layout
remain unchanged. Architecture and acceptance details belong in [design.md](design.md).
