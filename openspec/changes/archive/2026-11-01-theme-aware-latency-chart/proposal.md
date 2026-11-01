## Why

The illustrative latency chart predates the Rust-backed cache paths and no longer matches current measurements. It was drawn by hand from values that no committed tool reproduces, and its light card stands out on GitHub's and the documentation site's dark appearances.

## What Changes

Make the chart reproducible from benchmark output, add a dark variant, and document the refresh procedure. [design.md](design.md) records the decisions; [tasks.md](tasks.md) lists the work.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `public-library-documentation`: theme-matched, regenerable latency chart.
- `real-server-benchmarking`: logged median read latency.

## Impact

README, benchmark guides, contributor guide, decision records, chart assets, justfile, a new contributor script, a new cached-hit benchmark, the stream-cost runner's workload selection and the real-server benchmark's logging. No library runtime change.
