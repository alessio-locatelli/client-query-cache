## Context

See [proposal.md](proposal.md). The local direct read comes from the stream-cost benchmark's `read_heavy-small` report and the remote direct read from the real-server benchmark, which previously logged no latency.

## Decisions

- **Generated SVGs.** A stdlib script in `scripts/` renders both variants from one layout, so values, geometry and alternative text cannot drift between themes or documents. Hand-edited SVGs would repeat the previous drift.
- **One cached bar from a dedicated benchmark.** See the [latency chart composition decision](../../../../docs/development/decisions/latency-chart-composition.md).
- **Medians everywhere.** The real-server benchmark logs per-phase medians so every bar uses the same statistic.
- **Theme selection.** Both documents use `#gh-light-mode-only` and `#gh-dark-mode-only` fragments, which follow GitHub's appearance setting and the documentation theme's toggle. `<picture>` was rejected despite the fragments' deprecation: its `prefers-color-scheme` source follows the operating system's theme rather than GitHub's.
- **Explicit remote label.** The real-server benchmark accepts any deployment and cannot verify its type, so the recipe requires the remote deployment's name and the chart uses it as the label.
- **Selected stream-cost workload.** The stream-cost runner accepts `--workload`, so the recipe runs only `read_heavy-small` instead of the full matrix.
- **Dark palette.** The dark variant uses the same two hues stepped for a dark surface. Both palettes pass the dataviz palette validator for their surfaces.
- **No retained raw reports.** The recipe writes benchmark output to a temporary directory; the chart and commit body record the values.

## Risks / Trade-offs

- Direct reads vary between runs; contributors inspect the diff and rerun outliers.
- The recipe needs a configured real deployment; without one, rendering fails visibly instead of producing a partial chart.
