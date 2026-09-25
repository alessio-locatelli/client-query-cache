# Spec Delta

## MODIFIED Requirements

### Requirement: Controlled measurements are not generalized

The suite SHALL report monotonic wall time, benchmark-process CPU, and controlled MongoDB-container CPU for every controlled run. For every operation-bearing variant in a controlled run, it SHALL report the required per-variant latency distribution; an idle variant SHALL report the explicit zero-operation and no-latency-samples marker. If MongoDB-container CPU cannot be collected from the configured cgroup or runtime, setup SHALL fail and the run SHALL not produce a controlled report. Optional byte-proxy mode SHALL count only its direct benchmark path and SHALL refuse unsupported TLS, compression, discovery, or shared-connection configurations. CI SHALL retain these reports as workload and architectural cost evidence without using their absolute or cross-host timings as a pass/fail gate. This does not prohibit `performance-regression-guard` from gating a pull request on matched, same-run relative measurements of base and proposed implementations under its separate coverage and noise policy.

#### Scenario: Proxy mode is requested with compression

- **WHEN** a benchmark requests byte-proxy mode with compression enabled
- **THEN** the benchmark refuses the configuration rather than labelling its bytes as an unambiguous direct-path measure

#### Scenario: A workload variant is not primed

- **WHEN** a cache workload variant other than the oversized-result workload completes warmup without positive counter deltas for at least one cache admission and one cache hit for that variant
- **THEN** setup or report validation fails before sampled results are accepted

#### Scenario: Controlled container CPU is unavailable

- **WHEN** a controlled benchmark cannot collect MongoDB-container CPU from its cgroup or runtime
- **THEN** setup fails and the benchmark does not emit a controlled report with an incomplete CPU measurement

#### Scenario: A controlled report is slower than a historical report

- **WHEN** a controlled stream-cost report has a larger absolute timing value than a report from another run or host
- **THEN** CI retains the report without failing on that timing difference alone
