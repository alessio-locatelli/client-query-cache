# Design

## Context

See [proposal.md](proposal.md) for scope. Local untracked version 7/8 reports retain per-window percentile summaries, priming times and calibration failures. They omit per-request sequences and elapsed orchestration timers. These observations support block analysis but cannot reconstruct shorter windows.

## Decisions

Use a standalone NumPy research program, with its dependency isolated through PEP 723, rather than changing the acceptance runner. Vectorized resampling keeps the search inexpensive, but its random generator differs from the registered implementation; all new outputs are exploratory. The comparison grid and decision criteria live in the committed study plan, which is fixed before executing alternatives. Tasks 1.2 and 2.1 own the numerical implementation and execution.

Use paired historical blocks to estimate variability and an order-statistic simulation with known effects to test reduced sample populations. Historical subsampling is descriptive: it cannot validate a duration change. Simulate independent and clustered requests, block variation, drift and rare stalls separately so model assumptions remain inspectable. Retain a parameter when these models or missing observations cannot justify reducing it. Task 2.2 owns the recommendation.

Reusing live workers or caches would reduce setup, but would change freshness and block independence; exclude it from equivalent-work savings. Reusing immutable catalogue construction or unaffected baseline calibration could save time without reusing candidate observations, but reset fidelity and host drift require separate evidence under issue #278. No implementation of these optimizations is required here.

## Risks and trade-offs

- Aggregate quantiles hide within-window dependence. Simulation results are conditional, and cannot establish the frequency of host stalls or a validated optimum.
- Recorded worker priming overlaps across workers. Sum each window's maximum worker duration as a lower bound, never sum worker CPU or pretend it measures complete startup.
- A maintainer estimates approximately 24 hours for the previous session. Its scope and idle time are unknown; report this separately from reconstructed study bounds.
- Full reruns would consume the investigation budget without resolving the missing historical timers. Use retained evidence first and stop with explicit uncertainty when additional measurements would be disproportionate.
