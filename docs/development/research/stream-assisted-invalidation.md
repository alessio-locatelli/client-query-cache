# Stream-assisted invalidation evaluation

[Issue #257](https://github.com/alessio-locatelli/client-query-cache/issues/257) remains open: this study completes its projection-cost phase, not its net-benefit evaluation. The routing-only default and existing invalidation policy remain unchanged pending that evaluation. The [modeled hit shares](invalidation-scope.md#modeled-policies) do not establish net savings.

| Alternative                         | Decision                         | Evidence                                                                                                                                                   |
| ----------------------------------- | -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Full-document streaming by default  | Reject.                          | Full insert payloads charge uncached collections and grow with document size. This study establishes no compensating end-to-end benefit.                   |
| Bounded scalar insert partitions    | Unresolved; evaluate end to end. | Output remains small, but adds traffic to uncached collections; CPU noninferiority and net read savings are unproven.                                      |
| Field-name-only update dependencies | Unresolved; evaluate end to end. | Large updated values stay off the wire, but extracting names still costs work on every update. Net benefit and correct dependency extraction are unproven. |

## Protocol and scope

The acquisition and decision protocol was fixed before timing in [commit `829b4cc`](https://github.com/alessio-locatelli/client-query-cache/blob/829b4cc/openspec/changes/evaluate-stream-assisted-invalidation/design.md). Measurements were collected on 2026-10-17 with Python 3.14.7, PyMongo 4.18.2 and MongoDB 9.0.2, using the repository-pinned container image in an isolated single-member replica set limited to 2 CPUs and 2 GiB. The older churn report uses a different MongoDB version; its timings are not a matched baseline for this study.

The [runner](../../../research/invalidation_scope/stream_projection.py) compares no stream, the runtime's exact routing projection, one bounded insert scalar, update names, and full insert documents. The last mode retains the insert event's existing `fullDocument`; it enables neither `updateLookup` nor images. MongoDB documents the [insert payload and update-description semantics](https://www.mongodb.com/docs/manual/reference/change-events/update/). Full update lookups and pre/post images remain outside this evaluation.

Three blocks reverse mode order on the middle block. Each mode runs the existing 200 B, 2 KB and 20 KB seeded document profiles, idle windows, and read-heavy (10 reads/write), balanced (1), and write-dominant (0.1) traffic at 10 and 100 writes/second. Writes target either the read collection or an unread sibling in the same watched database. This models uncached collection costs while a database stream remains active; it does not instantiate a cache or measure actual hit retention. Every mode uses identical direct PyMongo reads and writes.

Active windows alternate inserts and updates. Half the updates increment a scalar; half replace a document-sized string. Every update must modify one document, and every stream must drain exactly the scheduled write count. Preflight checks scalar type/byte limits, missing values, large updates, removal, array truncation, replacement, and repeated-ID writes. All **630 windows** completed; all **47,520 expected stream write events** were observed. There were 540 active and 90 idle windows. Two-second windows took at most 2.099 seconds; achieved write rates were 95.3–100.0% of requested rates.

Server CPU covers the container and background MongoDB work. Client CPU covers the process, including reads/writes, decoding, logical BSON re-encoding and proxy/consumer threads. Re-encoding matches the runtime's logical-event counter; this experiment does not measure production guard CPU. Stream establishment, seeding and teardown are outside the operation timer. The existing helper samples container CPU and proxy counters around that timer, so those boundaries include sampling overhead. Wire bytes cover only the dedicated stream client's TCP connections, in both directions, without TLS or compression; writer/read connections bypass the proxy. Wire counters include MongoDB protocol framing but exclude TCP/IP headers and retransmissions. Logical bytes exclude protocol framing.

## Network measurements

Median additional received TCP bytes per **write**, paired against routing-only with matching block, size, workload, rate and target:

| Document bytes | Writes/s | Insert scalar | Update names | Full insert |
| -------------: | -------: | ------------: | -----------: | ----------: |
|            200 |       10 |          17.5 |         24.0 |       107.8 |
|            200 |      100 |          17.5 |         24.0 |       108.2 |
|          2,000 |       10 |          17.5 |         24.0 |     1,007.8 |
|          2,000 |      100 |          17.5 |         24.0 |     1,008.2 |
|         20,000 |       10 |          17.5 |         24.0 |    10,007.8 |
|         20,000 |      100 |          17.5 |         24.0 |    10,008.2 |

These figures average across the 50/50 insert/update mix. Scalar payloads add 35 logical bytes per insert; names add an average 48 bytes per update. Full insert payloads add approximately one whole document per insert. Routing-only events averaged approximately 365 logical bytes per write. Scalar/name payload cost stayed independent of document size for the tested one-field payloads.

Read-target and uncached-sibling writes had identical median scalar and name deltas: 17.5 and 24.0 bytes/write. At 20 KB and 100 writes/second, full inserts therefore add approximately **1 MB/second per watched database stream**, including uncached sibling writes with no saved reads from that sibling.

Median additional sent TCP bytes were zero for every candidate and both targets; individual paired deltas ranged from −3.6 to +3.6 bytes/write. Protocol traffic and sampling boundaries also affected received bytes: scalar deltas ranged from −56.6 to +91.6 and names from −50.1 to +98.1 bytes/write across active cells. Negative individual deltas do not remove the deterministic payload additions. Idle routing windows received a median 314 bytes/second and sent 252; other projections had essentially identical idle traffic. Median idle no-stream proxy traffic was zero; some windows included client-monitor traffic (up to 72 sent and 1,482 received bytes per window).

## CPU measurements

The table gives **candidate minus routing-only** CPU in microseconds per write: median, then full observed range. Each row aggregates 36 paired differences across three blocks, three active ratios, two rates and two targets. These are descriptive measurements, not confidence bounds.

| Document bytes | Candidate   |         Server Δ µs/write |     Client Δ µs/write |
| -------------: | ----------- | ------------------------: | --------------------: |
|            200 | Scalar      |     25.4 (−1,440.9…809.2) |    1.2 (−412.9…500.5) |
|            200 | Names       |   17.4 (−1,283.5…4,606.5) |   −4.9 (−938.4…409.9) |
|            200 | Full insert |    −65.2 (−1,082.7…620.6) |  −10.0 (−649.4…295.1) |
|          2,000 | Scalar      |  −14.8 (−1,083.4…2,287.4) |   28.7 (−526.8…476.5) |
|          2,000 | Names       |    0.6 (−1,707.5…3,022.1) |   −7.2 (−881.6…516.9) |
|          2,000 | Full insert |  −91.8 (−1,399.2…1,143.3) |  −14.7 (−744.6…457.6) |
|         20,000 | Scalar      |   56.7 (−5,691.0…4,450.9) |   11.7 (−335.5…438.3) |
|         20,000 | Names       |   26.8 (−3,673.0…2,153.0) |   13.5 (−359.7…861.7) |
|         20,000 | Full insert | −130.0 (−4,566.9…4,623.3) | 11.0 (−288.1…1,263.0) |

For the uncached sibling with 20 KB documents, median paired server/client deltas in µs/write were:

| Workload       | Writes/s | Scalar server/client | Names server/client | Full insert server/client |
| -------------- | -------: | -------------------: | ------------------: | ------------------------: |
| Read-heavy     |       10 |      −116.4 / −315.5 |    −1,171.3 / −36.4 |             604.4 / −83.9 |
| Read-heavy     |      100 |        120.2 / 148.4 |       30.9 / −114.9 |               3.4 / −27.6 |
| Balanced       |       10 |          284.9 / 9.2 |       −310.6 / 15.9 |              −521.6 / 8.5 |
| Balanced       |      100 |          96.2 / 27.5 |        53.5 / −45.3 |               −41.9 / 3.3 |
| Write-dominant |       10 |        653.3 / −24.0 |      −590.4 / −92.0 |             −750.8 / −8.5 |
| Write-dominant |      100 |       −115.9 / −73.4 |        33.0 / −51.5 |            −225.1 / −32.3 |

CPU precision cannot establish savings or noninferiority. As a noise check, within-block scalar server medians changed from +68.5 to −17.4 to +33.2 µs/write; names changed from +27.5 to +30.3 to −0.7. Name client medians changed from +12.2 to +11.2 to −17.5. Negative full-insert server medians likewise establish no compensating end-to-end benefit. Background work, short windows, mode order and timing boundaries limit attribution; ratios against unstable differences would mislead.

Across active conditions, median absolute server CPU was 2,584.0 µs/write without a stream and 3,581.1 with routing; client CPU was 1,360.3 and 2,372.8. These pooled medians include direct reads/writes and are not paired overhead estimates. Idle server CPU was approximately 18.0 ms/second without a stream and 19.2 with routing; client CPU was 0.8 and 1.8. These local observations are not production capacity estimates.

## Eligibility and remaining evaluation

The scalar prototype projects one fixed top-level integer, Boolean or UTF-8 string of at most 64 bytes. Floating-point/decimal values, null, missing, arrays, objects and longer strings return explicit unknown. The name prototype emits at most 32 names of at most 64 UTF-8 bytes each, including removed fields and truncated arrays; overflow returns unknown. It transmits no updated values. Bounding output does not bound server work: the expression extracts all updated names before deciding whether they fit.

A production policy must prove conservative fallback for unknown values and operations; BSON numeric equality and Boolean distinctions; array equality; null/missing semantics; collation; parent/child path overlap and ambiguous dotted/numeric paths; and replacement/deletion. Dependency extraction must cover filters, sorts, inclusion/exclusion projections and pipelines; a full-document feed depends on every returned field. Unsupported queries cannot silently retain entries. The [MongoDB update-event reference](https://www.mongodb.com/docs/manual/reference/change-events/update/) explains removal, truncation and path ambiguity.

The next phase is the focused end-to-end evaluation tracked in [#257](https://github.com/alessio-locatelli/client-query-cache/issues/257). Experimental guards are needed to measure actual hit retention, saved database reads and routing cost for each bounded policy independently; those prototypes are research tooling, not production adoption. The issue records the workload, correctness, resource and decision acceptance criteria. Another transport-only study cannot resolve them. Production adoption requires measured net benefit without reproducible regressions in unrelated workloads or uncached collections. Full-document streaming needs compelling evidence beyond a specially favorable read-heavy workload.

## Reproduction

Use the repository's [benchmark prerequisites](../../../CONTRIBUTING.md) and the pinned revision above. From the repository root:

```bash
bash -c 'set -euo pipefail; source scripts/testcontainers-bridge.sh; PYTHONPATH="$PWD" uv run python research/invalidation_scope/stream_projection.py --verify-only --out /tmp/agents/stream-assisted-invalidation/preflight.json'
bash -c 'set -euo pipefail; source scripts/testcontainers-bridge.sh; PYTHONPATH="$PWD" uv run python research/invalidation_scope/stream_projection.py --out /tmp/agents/stream-assisted-invalidation/matrix.json'
```

Output paths must be new. The default matrix takes roughly half an hour locally; run without concurrent validation or benchmarks. Raw JSON remains untracked and includes versions, harness SHA-256, per-window counts, CPU, logical bytes and both TCP directions. Match `(rep, size, kind, uncached, requested_writes_per_second)`, subtract routing-only, divide by the cell's writes, then take the median over the stated group to reproduce candidate deltas. Multiply CPU seconds by one million for µs/write. Idle rates divide by actual wall seconds. Regenerate raw results rather than committing them.
