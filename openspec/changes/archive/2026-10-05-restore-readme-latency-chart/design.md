## Context

See [proposal.md](proposal.md). The benchmark guide already uses one SVG with measured values and a footer identifying the workload, statistics, and logarithmic scale.

## Goals / Non-Goals

Expose that evidence in the README with a short caption. Preserve the existing measurements and the benchmark guide as the detailed source of truth.

## Decisions

- Reference the existing SVG from both documents. A separate README chart could be styled independently but would create a second measurement presentation to maintain.
- Use “Illustrative read latency” for the shared headline and scoped numeric descriptions for SVG accessibility and Markdown alt text. The “up to ~1,200×” headline is attention-grabbing but makes one Atlas comparison look more general when shown without the full guide.
- Keep only deployments, variability, and the methodology link in the README caption. Repeating the full guide caption would add statistical detail to the product introduction.

No new measurement or further research is needed: the figure and detailed explanation already exist.

## Risks / Trade-offs

- Two deployments use different summary statistics; retain the chart footer and link to the guide's explanation.
- The shared headline also changes on the benchmark page; update its accessible description with the same scope.
