# Spec Delta

## ADDED Requirements

### Requirement: Reports surface an explicit change-stream resource-cost comparison

For the `BALANCED` workload (concurrent insert and read traffic) at each configured data size, a controlled report SHALL present a raw-path and cache-path `container_cpu_seconds` value side by side as an explicit change-stream CPU-cost comparison, since the cache path watches a change stream and the raw path does not. When the report was produced with `--direct-path-proxy` enabled, it SHALL likewise present the raw-path and cache-path `direct_path_bytes_sent`/`direct_path_bytes_received` values side by side as an explicit change-stream network-cost comparison. Absent `--direct-path-proxy`, the report SHALL note the network-cost comparison as unavailable for that run rather than omitting it silently. Each path's values cover that path's whole run - its sampled reads and shared writes as well as, for the cache path, the change stream itself - so the report SHALL document that the difference between the two paths, not either value alone, approximates the change stream's added cost. This comparison is retained evidence, not a pass/fail gate, consistent with this capability's existing treatment of CPU and timing measurements.

#### Scenario: A controlled report includes the BALANCED workload

- **WHEN** a controlled report includes the `BALANCED` workload
- **THEN** the report presents the raw path's and cache path's `container_cpu_seconds` values side by side as the change-stream CPU-cost comparison

#### Scenario: The report was generated with byte-proxy mode enabled

- **WHEN** the report was generated with `--direct-path-proxy`
- **THEN** it also presents the raw path's and cache path's `direct_path_bytes` values side by side as the change-stream network-cost comparison

#### Scenario: The report was generated without byte-proxy mode

- **WHEN** the report was generated without `--direct-path-proxy`
- **THEN** the network-cost comparison is explicitly marked unavailable for that run, not silently omitted
