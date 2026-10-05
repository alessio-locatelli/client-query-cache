## Why

The README explains the cache's benefits but hides the existing latency illustration behind a documentation link. A compact chart makes the benefit visible while the benchmark guide retains the methodology and limitations.

## What Changes

- Restore the shared latency chart after the production-readiness paragraph.
- Add a short caption naming the deployments, noting variability, and linking to the benchmark guide.
- Rename the chart headline to “Illustrative read latency” and align its accessible descriptions.
- Preserve this compact presentation in the documentation specification.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `public-library-documentation`: require a scoped latency illustration in the README.

## Impact

README, the existing SVG, its benchmark-guide description, and documentation specifications. No new measurements, dependencies, or runtime changes.
