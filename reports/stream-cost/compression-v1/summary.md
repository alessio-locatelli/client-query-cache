# Wire-compression decision evidence

The September 2026 comparison retained in revision `925b40730def59bf21939f3d6644d9e973c830eb`
did not qualify Snappy, zlib or Zstandard over no compression. Four counterbalanced
blocks compared idle and balanced/write-dominant small/large workloads with and
without a change stream, on a single-member replica set limited to one CPU/1 GiB.
The retained decision file lacked a measured-source revision and complete host/
dependency metadata. Its publication revision is not proof of the measured
binary; numerical results therefore cannot serve as a current baseline.

The registered rule required at least 10% byte savings in every active cell,
server CPU and added CPU within 5%, and P95 invalidation lag within 10% of no
compression, across every block. All modes cleared the byte criterion but
failed CPU and/or lag checks. Snappy and zlib idle CPU deltas changed sign
between blocks. The result was inconclusive, with no compressor recommendation.

This supports measuring the trade-off, not a claim that compression is always
slower. Compression is caller-owned and affects every operation on the client;
the library does not choose it. Public usage belongs in the
[stream-cost guide](../../../docs/user/benchmarks/stream-cost.md#wire-compression).

To collect fresh evidence with complete provenance, use the contributor
environment and the runner's disposable replica set:

```bash
uv run -- python -m benchmarks.stream_cost.compression_run --output /tmp/agents/compression.json
```

The historical runner and thresholds remain available at the publication
revision above. Compare repeated blocks with matching workloads and environments,
and keep raw results untracked. Stream-minus-control approximates added stream
cost; it is not exact attribution.
