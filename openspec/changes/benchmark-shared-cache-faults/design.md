# Design

## Context

See [proposal.md](proposal.md) for motivation. The registration planner currently routes every comparison through steady-state workload cells. Owner controls already provide watch suspension, severing, history loss and admission races; the scenario tests supply the corresponding safety oracles.

## Goals / Non-Goals

This design measures scripted fault transitions. It does not estimate steady-state throughput, replace the independent-worker fault study, or reopen promotion decisions from v5.

## Decisions

Use a separate fault driver through the existing window dispatch, owner configuration and process group. A worker command loop keeps two synchronous and two asyncio managers alive across transitions. Probes report their own monotonic observation times; controller actions use the same host clock. Scenario details and the bounded observation policy are defined in `reports/shared-worker-cache/v6/registration.md`. Extract shared local-selection checks for use by both deterministic tests and trials. Keep fault state and observations out of the steady-state measurement loop.

An alternative is to instrument the offered-load scheduler. That would give latency under load, but adds observer overhead and restart accounting unrelated to this issue's four transition intervals. The scripted driver is chosen because it directly exercises the existing scenarios; no additional research is needed for this choice.

Each case has explicit applicability in v6. The driver records injection and recovery events, safety assertions and measured completion events. Readiness and publication are observed independently: a successful native read alone establishes neither. Missing events remain unavailable and fail applicable criteria. Analysis verifies the complete registered matrix rather than accepting whichever rows survived.

## Risks / Trade-offs

- Polling and control transport delay observations: record the cadence and describe durations as observed upper bounds.
- Killed or stopped processes can block teardown: resume stopped owners and reclaim killed children through the existing process lifecycle.
- Raw results are machine-dependent: retain them untracked and publish only reproduction commands and a concise measured summary.
