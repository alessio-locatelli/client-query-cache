# Show one cached-read bar measured on a busy CPU

## Context

The [latency chart](../../../CONTRIBUTING.md#latency-chart) illustrates how much a cache hit saves compared with a direct read in a local and a remote (Atlas M0) deployment. Direct reads differ by orders of magnitude between deployments. A cache hit never touches the network, so its latency does not depend on the deployment.

Cached-hit latency is sensitive to the client CPU's power state. On a host whose CPU slows down when idle, the same hit measured about 6–8 µs right after the CPU had been busy and about 20–60 µs after the CPU had idled. Both benchmarks that feed the direct-read rows idle the CPU between reads: misses, direct reads and network round trips leave it waiting. Their cached-read numbers therefore swing with how long the CPU had idled, not with the deployment. With the CPU kept busy just before measuring, one probe script running identical hit loops against both deployments measured the same median within a fraction of a microsecond.

## Decision

The chart shows one cached-read bar for both deployments. Its value is the median of repeated cache hits measured with no concurrent writes, immediately after keeping the CPU busy, by a dedicated benchmark (`benchmarks/cached_hit_latency.py`). Direct-read rows remain medians from the stream-cost and real-server benchmarks. Every bar is a median.

## Alternatives considered

**One cached bar per deployment.** Two bars imply that the deployment changes hit latency. Any gap between them comes from CPU power state, document shape and statistic differences between the benchmarks, so the chart would present a measurement artifact as a deployment property.

**Cached value from the real-server benchmark.** Its concurrent writer invalidates entries during the cached phase. Each resulting miss idles the CPU for a network round trip, so later hits run on a slowed CPU and the median changes from run to run depending on where the miss lands. Warming the CPU before the phase makes this worse: a longer phase overlaps more writes.

**Cached value from the stream-cost benchmark.** Its cached variant interleaves hits with misses, so hits follow network waits and inherit the same power-state noise.

**Cached value measured after idling.** It describes a lightly loaded client CPU rather than the cache, is not reproducible between runs, and overstates hit cost for busy application servers, where caching matters most.

## Consequences

The cached bar is stable between runs and shows the cache's cost rather than the host's power management. It is a best case for a busy CPU; the benchmark guide states that idle CPUs can make hits several times slower. The chart's cached value needs a local container runtime but no remote deployment.

This decision assumes that a cache hit involves no network or deployment-dependent step.
