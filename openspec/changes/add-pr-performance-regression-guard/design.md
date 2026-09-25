# Design

## Context

See [proposal.md](proposal.md) for the gap. The manual [stream-cost workflow](../../../.github/workflows/stream-cost-benchmark.yml) runs the 12-variant controlled matrix for one revision and uploads reports. The [Python-validation workflow](../../../.github/workflows/test.yml) runs tests on relevant pull requests, including benchmark tests, but makes no timed base-versus-head comparison. The existing matrix measures raw/cache cost and captures server CPU, latency distributions, and stream telemetry; its report schema and calibration rules serve architectural analysis. The guard needs a narrower, same-host comparison of the shipped path itself.

## Goals / Non-Goals

**Goals:**

- Keep a required PR check stable while spending benchmark time only when Python code, runtime dependencies, or the guard changes.
- Detect a substantial slowdown in a small set of representative, existing cache behaviors, with data and validity checks sufficient to identify what became slower.
- Keep baseline and proposed code on one runner under matched runtime, data, and workload conditions.

**Non-Goals:**

- Certify absolute latency or capacity, replace the controlled stream-cost reports, or infer server CPU and network cost from a local timing ratio.
- Gate the full workload matrix, calibrated invalidation delivery lag, or the incremental-encoder architectural decision on every PR.
- Detect every smaller regression or every workload-specific performance change.

## Decisions

### Protect four focused paths

The initial guard covers synchronous and asynchronous cached `find_one` hits, bounded admission of a small multi-document `find` result, and routing a change event that invalidates a populated entry. These exercise the public read wrappers, the shared key/codec/cache core, and the stream invalidation route. Each case checks the expected hit, admission, or invalidation counter and returned result outside the timed region, so a bypass or wrong answer cannot appear as a fast sample. A small and a moderate document profile cover fixed overhead and materialization growth without reproducing the 12-case matrix. The implementation may combine the two read-hit modes into one workload definition with separately reported cases; each remains independently guarded.

The disposable replica-set fixture and `benchmarks/stream_cost` seeded document generators, warmup/priming checks, and observability snapshots provide realistic state and outcome validation. A thin guard runner can reuse those pieces while avoiding the controlled report schema, byte proxy, container-CPU requirement, clock-offset calibration, and architectural decision runner. The guard measures complete operations or bounded batches, not a mocked helper in isolation. Alternative: run the full matrix twice. That would increase runner time, amplify server noise, and answer a broader cost question than the PR guard needs.

### Compare exact revisions using one trusted workload definition

The comparison records the target base SHA and the PR's tested merge result SHA from the same event. It uses the workload definition from the base revision for both implementations so a PR cannot make its own comparison easier by changing the timed work. Base and proposed implementations execute in separate processes/environments on the same runner and Python version; each uses its revision's declared locked dependencies, so dependency changes are included in the proposed behavior. The same seeded documents, query shapes, cache configuration, and server topology apply to both. Each block resets application/cache state and warms both sides before timing. The timed order alternates across blocks to limit runner and server-warmth bias.

If a PR changes the guard definition, CI also validates the proposed guard's own behavior, while the base definition remains authoritative for that PR comparison. A newly added case becomes protective once its definition reaches the base branch. If a legitimate public-interface change makes the base workload inapplicable to the proposed implementation, the check reports a measurement failure with the incompatible case; maintainers resolve that migration explicitly rather than letting it silently skip. Alternative: use separate head and base workload definitions. Their timings would not describe the same work and would allow accidental or intentional benchmark drift.

The introducing PR is the one bootstrap exception: its base revision has no guard definition. Review and test the new definition against both revisions, plus a deliberately slowed candidate, before merging it. Do not make its status required until that definition is on the base branch. Subsequent PRs use the base definition as described above; lack of that expected definition is then a measurement failure.

### Fail only on clear relative regressions

The gate predeclares a 30% relative slowdown boundary for each case, a fixed sample budget, and a stability rule before reading results. Timed batches must be long enough that clock resolution and one-off scheduling delays do not dominate. Repeated, counterbalanced blocks yield a robust central comparison and a variability bound. A performance failure requires the conservative bound for the head/base ratio to lie beyond the material boundary; neither a single outlier nor a ratio with overlapping uncertainty is enough. The final method and sample budget can be selected during implementation from a short clean-base self-comparison pilot, but they must be fixed in the checked-in guard before it evaluates a PR and tested against injected slowdowns. This is a calibration of the guard's noise behavior, not a threshold chosen from the PR's observed result.

A valid but inconclusive comparison reports a warning and succeeds; it does not certify that the path is fast. Missing baseline, changed workload semantics, failed outcome checks, or an exhausted measurement setup reports a distinct operational failure. This prevents a broken guard from appearing green. An explicit timeout limits CI cost. Alternative: compare against retained millisecond limits or previous-host artifacts. Host and dependency differences would dominate. Alternative: fail any positive slowdown or every inconclusive sample. That would make ordinary runner noise a frequent blocker.

### Give the guard its own PR check and diagnostics

Use a dedicated, unprivileged pull-request check with a stable name. It starts for every PR so required-check configuration does not strand documentation-only changes, but it runs timed work only if the changed files include Python, dependency metadata/lockfile, or guard/workflow inputs. This avoids a narrow workflow-level path filter while covering shared Python helpers outside `src/`. A concise job summary shows each case's base and head timing, relative change, variability bound, outcome validation, decision, both revisions, and workload identity. A bounded machine-readable result is retained on failures or inconclusive runs. No application documents, credentials, or raw environment dump are stored.

The existing manual `stream-cost-benchmark` workflow stays available for controlled cost and architectural analysis. Its reports remain observational and are not consumed as the guard's baseline. No routine PR checkbox is added. A documented intentional slowdown retains the red measured result. Before enabling a required status, repository administrators must configure an auditable merge-rule exception limited to designated maintainers; the maintainer records the accepted cost and compensating reason in PR review, then exercises that external exception for the specific merge. A PR author cannot suppress the job with a label or checkbox. The repository currently documents no such exception, so configuration and verification of this control are rollout prerequisites, not existing capabilities to assume. If administrators cannot provide it, required-check activation remains blocked and this limitation is reported rather than quietly enabling a bypass.

## Risks / Trade-offs

- **A noisy shared runner obscures a real regression** → Use paired, counterbalanced blocks and a conservative uncertainty rule; show inconclusive results, then tune only from a clean-base pilot. The 30% boundary deliberately leaves smaller regressions to targeted investigation.
- **The baseline workload cannot run against a changed API** → Fail with an explicit compatibility diagnosis and require a reviewed workload migration or human-controlled exception.
- **A database-backed case adds CI time** → Limit cases, data sizes, repeats, and total runtime; reuse one disposable topology for the comparison and leave expensive stream-cost analyses manual.
- **A clean workflow status is mistaken for merge protection** → Configure the stable guard status as required in repository merge rules and verify that a deliberately slowed PR cannot merge through normal rules.
- **A benchmark-only PR changes the future guard** → Validate the proposed guard and retain the base definition for the current comparison; review new workload coverage before merge.

## Migration Plan

Implement and validate the cases and decision logic, then run a clean-base self-comparison and an intentionally slowed candidate on CI-like runners. Confirm ordinary runs are stable within the boundary and the seeded slowdown fails. Add the pull-request workflow with a stable status. For the introducing PR, run the reviewed new workload against both revisions because the base lacks that definition. Once it merges and the pilot is acceptable, have repository administrators configure and verify the maintainer-only exception before marking the guard check required in merge rules. Revert the guard workflow and required-status setting together if it proves persistently noisy; the manual benchmark workflow and reports remain available throughout.
