# Stream-assisted invalidation evaluation

[Issue #257](https://github.com/alessio-locatelli/client-query-cache/issues/257) evaluates whether narrower invalidation pays for a larger change stream. Real cache reads confirm that both bounded policies save database commands, client CPU and server CPU under the tested churn. Neither provides those savings in uncached or unrelated workloads, which still pay additional stream and routing costs. Keep the routing-only default and existing production invalidation policy. These results establish targeted usefulness; they do not establish broadly applicable gains from changing the default.

| Alternative                         | Decision                                            | Evidence                                                                                                                                   |
| ----------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Full-document streaming by default  | Reject.                                             | Insert payloads grow with document size and charge uncached collections. No measured broad benefit justifies that cost.                    |
| Bounded scalar insert partitions    | Useful under insert churn; retain existing default. | Actual feed/count retention saves about 1,941–1,988 reads per 4,096 operations. Uncached inserts still add 35 bytes each and routing work. |
| Field-name-only update dependencies | Useful for independent counts; retain default.      | Counts retain 100% hits under `views` updates, saving about 974–1,019 reads. Uncached updates still add 47 bytes each and routing work.    |

## Projection-cost protocol

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

## Projection-only CPU measurements

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

## End-to-end protocol and correctness

The [end-to-end acquisition](../../../research/invalidation_scope/end_to_end.py) was registered and frozen at [commit `f0f9782`](https://github.com/alessio-locatelli/client-query-cache/tree/f0f9782797032b90bdc74b0b49022af882cbcb13). It uses the same Python, driver, MongoDB and pinned image, with a 2-CPU, 4 GiB isolated server. The larger memory limit accommodates three collections of 20,000 documents at the largest size. The interrupted acquisition was discarded after the host shutdown; the complete decision acquisition was restarted with the same parameters. Pilots are excluded.

The [experimental guards](../../../research/invalidation_scope/guards.py) reuse native `CachedCollection` reads, cursor capture, BSON serialization, LRU, identity guards and stream lifecycle. Insert routing assigns the fixed author-filtered feeds/counts to per-author generations with a shared O(1) fallback fence. Field routing assigns author counts a separate generation; `views` updates retain them, while full-document feeds continue to invalidate. Direct PyMongo and the native routing projection are controls. This is a fixed-query experiment, not a generic query-dependency parser or a public API change.

Before acquisition, real-server qualification checked known and unknown insert values, numeric/Boolean distinctions, arrays, null/missing, relevant field changes, removal, array truncation, overflow, replacement/deletion and capture/admission races. Affected in-flight captures decline admission; an unrelated insert preserves admission only for its independent partition. Unsupported queries use the original adapter.

The churn matrix completed **192 cells**: four forward/reverse blocks, three exact BSON document sizes, two separate write mixes, 100/10 reads per write, and direct/current/insert/field paths. Each cell warms the four read classes over 32 hot authors out of 500, then executes 4,096 reads with 40 or 409 writes. Writes and reads are identical within each matched block. **786,432 reads** completed, and all **32,328 expected stream write events** drained on cached paths. An independent oracle compares returned documents/counts; native cache counters reconcile with observed `find`/`aggregate` commands. Application and stream proxies separately measure both TCP directions, without TLS/compression. CPU covers the process and container as in the transport phase; elapsed time includes writes, reads, oracle work and final event drain. Read latency measures only the individual read call. Setup, warming and restoration are outside timing.

There were 78 stale reads in insert-partition churn, all before the latest relevant event had applied at read start: 0.079% of that policy's 98,304 reads, or 0.159% of its eligible feed/count reads. Other paths observed none. No wrong result was observed after the latest relevant event applied. Retention increases exposure to the existing asynchronous stream window; saved reads do not imply read-after-write freshness.

## Measured read savings and net benefit

Direct PyMongo always issues 4,096 database reads per cell. Current invalidation issues a median 1,948 at 100 reads/write and 2,038 at 10. Native identity reads already retain hits; the opportunity is in feeds/counts. Insert partitions reduce total database reads to medians of 7 and 50, respectively. Field dependencies reduce them to 974 and 1,019. Insert feed/count hit shares have medians of 99.66% and 97.56%, compared with current shares of 4.88% and 0.49%. Field-dependent counts retain 100% hits; feeds remain subject to native invalidation.

Each percentage below is the median **paired** candidate/current change across four blocks, with size, mix and ratio fixed. Negative values mean less work/time/traffic. TCP totals combine application and stream traffic in both directions, so they include saved reads and the larger stream. Separate CPU columns avoid assuming interchangeable client/server resources.

| Policy / write mix | Document bytes | Reads/write | Client CPU Δ | Server CPU Δ | Elapsed Δ | Total TCP Δ |
| ------------------ | -------------: | ----------: | -----------: | -----------: | --------: | ----------: |
| Insert / inserts   |            200 |         100 |       −73.9% |       −90.5% |    −72.8% |     −98.30% |
| Insert / inserts   |            200 |          10 |       −25.4% |       −34.7% |    −26.0% |     −86.06% |
| Insert / inserts   |          2,000 |         100 |       −75.0% |       −90.9% |    −74.8% |     −99.29% |
| Insert / inserts   |          2,000 |          10 |       −35.4% |       −40.0% |    −34.4% |     −94.29% |
| Insert / inserts   |         20,000 |         100 |       −78.1% |       −93.3% |    −77.9% |     −99.42% |
| Insert / inserts   |         20,000 |          10 |       −51.8% |       −54.1% |    −46.2% |     −95.49% |
| Fields / updates   |            200 |         100 |       −29.8% |       −59.7% |    −35.3% |     −12.10% |
| Fields / updates   |            200 |          10 |        −8.5% |       −28.1% |    −16.8% |     −10.64% |
| Fields / updates   |          2,000 |         100 |       −32.9% |       −60.9% |    −37.1% |      −1.57% |
| Fields / updates   |          2,000 |          10 |       −15.5% |       −31.3% |    −19.0% |      −1.51% |
| Fields / updates   |         20,000 |         100 |       −24.9% |       −48.9% |    −32.2% |      −0.16% |
| Fields / updates   |         20,000 |          10 |       −16.6% |       −32.8% |    −21.1% |      −0.16% |

Both client and server CPU fell in all 24 matched cells per hypothesis, and TCP totals fell throughout. Elapsed time fell in 24/24 insert comparisons and 23/24 field comparisons. The exception was a 200 B, 100-reads/write field cell with elapsed time +25.0% despite client CPU −20.9% and server CPU −53.3%; its cause was not isolated, and it remains in the results. Under the opposite write mix, median elapsed/client/server changes were +0.7%/+1.2%/−0.5% for insert guards during updates and −2.1%/−2.4%/−2.3% for field guards during inserts, with mixed block directions and no systematic read-retention benefit.

Insert routing reduces total TCP by avoiding document reads; the median per-cell total falls from 4.98–398.37 MiB with current routing to 0.085–17.98 MiB. Field routing saves count commands, so its absolute saving remains approximately 0.60–0.61 MiB even as full feed payloads grow. The separately metered stream still adds exactly 35 bytes/insert or 47 bytes/`views` update in matched churn cells. These are measured net gains, not modeled hit shares credited against an unimplemented guard. Process CPU includes the oracle and byte-proxy threads, so its percentages should not be transferred to an uninstrumented production client.

At 2 KB and 100 reads/write, median per-cell feed P50/P99 changed from 438/1,092 µs to 55/164 µs with insert routing; count latency changed from 369/811 µs to 21/55 µs. Field routing changed count P50/P99 from 368/749 µs to 32/62 µs. These read-call measurements exclude oracle work and final event drain.

## Uncached/unrelated costs and warm hits

The first control acquisition completed **96 eight-second windows**, with 2 KB documents, 10/100 writes per second, separate insert/update mixes, three cache policies, and four counterbalanced blocks. One scenario writes an uncached sibling while reading warmed target entries. The other writes a resident target while reading an unrelated collection. All **42,240 reads were hits**, all **42,240 writes drained**, and no database reads were saved by either prototype. Application wire traffic matched exactly. Stream traffic added 35 bytes/insert or 47 bytes/update in every matching block, including uncached collections. Windows finished within 8.00024 seconds.

The eight-second CPU measurements varied. Across matching control groups, median total process changes ranged from −3.5% to +3.3%, and server changes from −7.6% to +6.9%; most groups had mixed block directions. Names on uncached updates at 10/s were higher in all four blocks (+3.3% client/+6.9% server medians). Routing CPU increased in all matching control comparisons except one field/unrelated/10-s comparison. These observations prompted the registered longer comparisons below; they are preserved rather than replaced.

The longer controls were registered at [commit `d0cba87`](https://github.com/alessio-locatelli/client-query-cache/tree/d0cba879ef2c4ec001487db59f6ebc70ecbc7f0a) before acquisition. They compare each policy against current routing with its matching write mix, at 100 writes/second: four forward/reverse blocks, uncached/unrelated scenarios, **32 windows of 32 seconds**. All **102,400 writes and hit-only reads** completed, with zero database reads or stale results; maximum duration was 32.014 seconds. Application traffic again matched exactly. Additional logical bytes were exactly 35/insert or 47/update. Additional stream TCP had the same medians; one names window added another 136 protocol bytes (47.0425 bytes/write).

Candidate minus current CPU, in **µs/write**, gives the paired median and full four-block range. Routing is a subset of client CPU, measured with the stream thread's CPU clock around native plus experimental routing. Baseline total process/container CPU was approximately 5.7–6.0/6.6–6.9 seconds per 32-second window.

| Policy | Control   |      Client CPU Δ |      Server CPU Δ |     Routing CPU Δ |
| ------ | --------- | ----------------: | ----------------: | ----------------: |
| Insert | Uncached  |  23.2 (−9.6…83.6) |  19.7 (0.6…126.9) |  2.38 (2.24…3.09) |
| Insert | Unrelated |  1.6 (−13.6…30.4) |  2.0 (−11.2…18.1) |  6.09 (5.09…7.05) |
| Fields | Uncached  |  1.2 (−12.8…15.8) | 33.1 (−32.9…69.4) |  2.81 (2.55…3.00) |
| Fields | Unrelated | −4.7 (−19.7…79.4) | 58.1 (−13.8…96.0) | 7.42 (6.76…11.19) |

Routing CPU increased in every longer comparison. Insert/uncached server CPU also increased in all four blocks, with a median +0.94%; other total-CPU groups retained mixed directions. Longer windows therefore improve the cost evidence without establishing a precise universal server/client increment. In the insert/unrelated control, every read class's P50 increased in all four blocks, with paired median increases of 1.4–2.0%. `_id` P99 increased in all blocks for both uncached and unrelated controls: medians +10.2% and +12.2%, respectively. Field/uncached count P99 increased in all blocks (+3.7% median); other field-control latency directions were mixed. There is no evidence here that narrower retention is free for workloads that cannot use it.

Warm-hit measurements completed **576,000 native hits** in four counterbalanced blocks, three batches of 4,000 hits per class/policy, with zero driver reads. Median current CPU per hit was 48.53 µs for feeds, 13.91 for counts, 14.80 for compound identity reads and 7.51 for `_id`. Paired CPU changes for insert guards were +0.10%/+0.32%/−1.94%/+0.32%; field guards were +1.12%/+0.02%/−2.73%/+0.49%. The unchanged identity paths also shifted, and most affected-path comparisons had mixed directions. These measurements do not resolve small hit-path costs or establish statistical noninferiority.

## Eligibility and interpretation

The scalar projection permits one fixed top-level integer, Boolean or UTF-8 string of at most 64 bytes. Floating-point/decimal values, null, missing, arrays, objects and longer strings return explicit unknown. The end-to-end partition guard accepts only integer authors; other projected scalar types also trigger its conservative fallback. The name projection emits at most 32 names of at most 64 UTF-8 bytes each, including removed fields and truncated arrays; overflow returns unknown. It transmits no updated values. Bounding output does not bound server work: the expression extracts all updated names before deciding whether they fit.

A production policy must prove conservative fallback for unknown values and operations; BSON numeric equality and Boolean distinctions; array equality; null/missing semantics; collation; parent/child path overlap and ambiguous dotted/numeric paths; and replacement/deletion. Dependency extraction must cover filters, sorts, inclusion/exclusion projections and pipelines; a full-document feed depends on every returned field. Unsupported queries cannot silently retain entries. The [MongoDB update-event reference](https://www.mongodb.com/docs/manual/reference/change-events/update/) explains removal, truncation and path ambiguity.

The fixed-query prototypes exercise conservative guards without claiming a generic dependency extractor. Their benefits pay for their measured projection/routing cost on the tested matching churn. Uncached and unrelated writes demonstrate the cost with no compensating saved reads; a universal default would impose it regardless of workload. Retain the small routing-only default under the issue's no-unrelated-degradation criterion. This decision does not classify the bounded techniques as poor investments: their targeted gains are demonstrated independently. No further transport-only or end-to-end study is left as an unmet acceptance criterion of #257. Single-member local measurements establish neither production capacity nor a universal break-even rate.

## Reproduction

Use the repository's [benchmark prerequisites](../../../CONTRIBUTING.md). The transport acquisition is pinned to `829b4cc`, the first end-to-end acquisition to `f0f9782`, and the longer controls to `d0cba87`. The latter preserves the guards and default measurement loops; its `--focus` flag selects only the registered comparisons. From the repository root at the corresponding revision:

```bash
bash -c 'set -euo pipefail; source scripts/testcontainers-bridge.sh; PYTHONPATH="$PWD" uv run python research/invalidation_scope/stream_projection.py --verify-only --out /tmp/agents/stream-assisted-invalidation/preflight.json'
bash -c 'set -euo pipefail; source scripts/testcontainers-bridge.sh; PYTHONPATH="$PWD" uv run python research/invalidation_scope/stream_projection.py --out /tmp/agents/stream-assisted-invalidation/matrix.json'
bash -c 'set -euo pipefail; source scripts/testcontainers-bridge.sh; uv run python -m research.invalidation_scope.end_to_end --suite verify --out /tmp/agents/stream-assisted-invalidation/guards.json'
bash -c 'set -euo pipefail; source scripts/testcontainers-bridge.sh; uv run python -m research.invalidation_scope.end_to_end --suite churn --reps 4 --reads 4096 --out /tmp/agents/stream-assisted-invalidation/churn.json'
bash -c 'set -euo pipefail; source scripts/testcontainers-bridge.sh; uv run python -m research.invalidation_scope.end_to_end --suite controls --reps 4 --seconds 8 --out /tmp/agents/stream-assisted-invalidation/controls.json'
bash -c 'set -euo pipefail; source scripts/testcontainers-bridge.sh; uv run python -m research.invalidation_scope.end_to_end --suite micro --reps 4 --out /tmp/agents/stream-assisted-invalidation/hits.json'
bash -c 'set -euo pipefail; source scripts/testcontainers-bridge.sh; uv run python -m research.invalidation_scope.end_to_end --suite controls --focus insert --reps 4 --seconds 32 --out /tmp/agents/stream-assisted-invalidation/insert-long.json'
bash -c 'set -euo pipefail; source scripts/testcontainers-bridge.sh; uv run python -m research.invalidation_scope.end_to_end --suite controls --focus fields --reps 4 --seconds 32 --out /tmp/agents/stream-assisted-invalidation/fields-long.json'
```

Output paths must be new. Run sequentially without concurrent validation or benchmarks. The transport matrix takes roughly half an hour locally, the first end-to-end suites roughly half an hour, and longer controls roughly 18 minutes. Raw JSON remains untracked and includes versions, source SHA-256, counts, CPU, logical bytes and both TCP directions; end-to-end output also includes commands, cache/footprint deltas, routing CPU, stale counts and per-class latency. Regenerate raw results rather than committing them.

For transport deltas, match `(rep, size, kind, uncached, requested_writes_per_second)`, subtract routing-only, divide by writes, then take the median over the stated group. CPU seconds × one million gives µs/write; idle rates divide by actual wall time. For end-to-end pairs, match `(rep, size, mix, scenario, reads_per_write, control_rate)` and use `current` as baseline. Percent changes are `100 × (candidate / baseline − 1)` before taking medians. Total TCP sums sent/received bytes from both proxies. Saved reads subtract summed `driver_reads`; each churn class has 1,024 measured reads. Warm-hit comparisons first take each block's median over its three batches, then pair against current and take the median across blocks. Reported ranges are observations, not confidence intervals.
