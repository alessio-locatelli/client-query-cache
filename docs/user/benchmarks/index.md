# Benchmarks

## Is caching a good fit for your workload?

Before enabling the cache for a workload, weigh these factors — each is covered by the [retained reports](stream-cost.md#reports) or by
[deployment guidance](../operations/deployment.md):

- **Read/write ratio.** Caching benefits read-heavy and balanced workloads the most; a write-dominant workload pays
  the cost of processing a change-stream event and invalidating cache entries on every write, while a shrinking
  share of reads ever reach a warm entry before it's invalidated again. Compare the `read_heavy`, `balanced`, and
  `write_dominant` [reports](stream-cost.md#reports) for a sense of the difference.
- **Topology and process model.** Caching a database costs one change-stream cursor per active database per
  `CacheManager` instance (see [capacity estimation](../operations/deployment.md#capacity-estimation)); a high-fan-out or
  short-lived-process deployment, or a manager watching many databases, pays that fixed cost more often or more
  times over, which can outweigh the benefit for that deployment shape even when the read/write ratio looks
  favorable.
- **Document size.** Larger documents cost more to admit and encode into the cache and are more likely to exceed
  `max_entry_bytes` and bypass entirely. Compare the small/medium/large report variants for a workload with a
  document size similar to yours.
- **Stream health.** Caching only helps while a database's change stream is healthy; a database with frequent
  network interruptions, or a MongoDB server or topology that can't provide change streams at all (see
  [system requirements](../getting-started/installation.md#requirements)), bypasses the cache for that traffic instead of
  raising an error.

None of the [reports](stream-cost.md#reports) establishes a performance guarantee for your own workload, host, or MongoDB topology —
use them to decide what to measure on your own deployment before relying on the cache in production.

## Illustrative read latency

![Cached reads are up to about 1,200 times faster than a direct read, and roughly the same speed whether the server is local or a real remote deployment. Direct local server read 120 microseconds, direct real deployment (Atlas M0 free tier) read 79.4 milliseconds, cached read about 61 microseconds either way. Bars use a logarithmic scale.](../assets/benchmark-latency-light.svg)

Read latency across two different deployments, so you can see the range: the local-server row is the median from one of the [retained local benchmark reports](stream-cost.md); the M0-deployment row is the mean of one batch from the [real-server benchmark](https://github.com/alessio-locatelli/client-query-cache/blob/main/CONTRIBUTING.md#real-server-benchmark) against a free-tier Atlas (M0) cluster — plotted on a logarithmic axis given the size of the gap. Cached-read latency barely moves between the two, since a cache hit never touches the network. Neither number is a universal performance guarantee for your own workload or deployment — see [Stream cost benchmarks](stream-cost.md) for the full local workload matrix and how to reproduce it.

See [stream cost measurements](stream-cost.md) for the retained workload matrix, await-time and compression evidence, reproduction commands, and measurement limitations.

## Performance regression guard

The repository compares representative cache operations between the base and proposed revisions of a pull request on the same runner. This check helps detect cache performance regressions; it does not establish a performance guarantee for your application or replace the broader stream cost measurements. Maintainers can read the [guard policy source](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/performance-regression-guard.md) for workloads, thresholds, reports, and review exceptions.
