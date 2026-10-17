# Design

## Context

See [proposal.md](proposal.md) for motivation. The existing simulator predicts invalidations; it does not account for projection, transport or decoding. The database stream also observes collections without resident entries.

## Decisions

Use the existing isolated replica set, seeded document-size profiles, dedicated clients, byte proxy and container CPU measurement. A standalone runner compares no stream, routing metadata, insert scalars, update names and full insert documents, with identical raw reads and writes. This isolates added stream cost without inventing a production guard or crediting an unimplemented hit-rate benefit. No images or event lookups are enabled.

The scalar experiment projects one fixed top-level `index` field. Integer and Boolean values are bounded; strings qualify only through 64 UTF-8 bytes. Floating-point/decimal values, missing, null, arrays, objects and larger strings produce an explicit unknown outcome. The update experiment returns changed, removed and truncated-array names, never updated values; over 32 names or any name exceeding 64 UTF-8 bytes produces unknown. It preserves the distinction between known-empty and unknown. These bounds deliberately trade selectivity for predictable payload size. Unknown and non-applicable operations require collection invalidation in any subsequent design.

Full insert payloads provide a cost control: they require no lookup but scale with document size. They could route arbitrary partitions; their disadvantage is charging every insert, including unrelated collections. `updateLookup` and pre/post images have additional I/O or storage costs and are excluded by the issue. No further investigation of those alternatives is needed here.

### Acquisition and decision protocol

Before timing, exercise projection semantics against real MongoDB, including scalar boundaries, absent fields, large updates, removal, array truncation and replacement. The runner must drain and count every write event, fail visibly on consumer errors or timeout, and exclude stream establishment and teardown from timed windows.

Measure three counterbalanced blocks of the existing small/medium/large profiles. Each block includes idle and read-heavy (10 reads/write), balanced (1) and write-dominant (0.1) workloads at 10 and 100 writes/second, with writes either to the read collection or an uncached sibling. Active writes alternate inserts and updates; updates alternate a scalar increment and a document-sized string replacement. Windows last two seconds, with actual duration and achieved write rate recorded. Record server CPU, process CPU, logical BSON, and both wire directions. Reads are direct PyMongo on every path. Process CPU includes writers, readers, consumer and byte-proxy threads, so paired deltas approximate stream cost rather than isolating decoder CPU. No-stream controls establish absolute stream overhead; routing-only is the candidate baseline.

The preregistered acquisition above measures transport cost only. Production adoption requires a measured end-to-end benefit and no reproducible regression in uncached or unrelated workloads. Record ranges and medians without interpreting short-window CPU ratios as precise estimates. The end-to-end phase below resolves the remaining acceptance criteria in [#257](https://github.com/alessio-locatelli/client-query-cache/issues/257) within this change.

An end-to-end experimental guard is permitted for research without first proving its own benefit. A simulator alone cannot establish actual retained hits, saved reads or routing work.

### End-to-end prototypes

Use the unmodified `CachedCollection`, cursor capture, BSON serialization, LRU, identity guards and change-stream lifecycle. Research adapters assign virtual namespaces to the fixed eligible feed/count queries, and instrument the native stream projection/router in the isolated process. Insert partitions share an O(1) conservative fallback fence plus per-author generations; generation composition participates in native lookup and capture/admission checks. This avoids an artificial scan over all partitions on each fallback. Field dependencies use a separate namespace generation for author-filtered counts; `views` updates retain those counts, while feeds and identity reads keep native routing. Unsupported query shapes use the original collection adapter. These are fixed-workload prototypes, not a generic production dependency parser.

Before timing, prove known/unknown inserts, numeric/array/null/missing outcomes, relevant and unrelated updates, removal/truncation, replacement/deletion, supported-query freshness after stream application, and capture/admission races. Compare every completed window's returned values against an independent oracle; stale observations are permitted only when a relevant event had not applied at read start. Reconcile native driver read commands with cache misses/bypasses and drain every event.

Pilot acquisition cost and correctness without using pilot timings for decisions. Then pin the final acquisition parameters and decision criteria before the decision run. The planned churn matrix uses the existing 20,000-document/500-author/32-hot-author/four-read-class workload, separate inserts and `views` updates at 100 and 10 reads/write, and 200 B/2 KB/20 KB documents. Compare direct PyMongo, current invalidation and both independent prototypes in counterbalanced blocks. Dedicated application and stream proxies measure saved-read traffic and added stream traffic separately. Record end-to-end CPU/latency/throughput, per-class hits and observed stale exposure, resident bytes, plus stream-thread routing CPU per event.

Use matched balanced controls at 10 and 100 writes/second with uncached sibling writes and unrelated reads while the target collection remains resident. The existing transport matrix already covers the broader read/write and size matrix; these controls add actual guard routing and cache-hit overhead. Add repeated warm-hit measurements to distinguish hit-path cost from read avoidance. Keep experiments bounded by the pilot's measured acquisition cost, rather than inheriting a multi-hour duration.

Decide each hypothesis separately from actual saved reads and total resource costs. Repeatable benefit in the targeted workload establishes usefulness there, not a safe universal default. Any repeatable additional cost with no compensating benefit in an unrelated/uncached control blocks default adoption under the user's constraint. Do not reject a bounded policy merely because an experiment was omitted or inconclusive; investigate noise and gather the evidence needed for the decision. Full-document streaming remains outside production adoption unless its additional costs have compelling broadly applicable benefits.

### Decision-run registration

The 16-cell 2 KB pilot used 4,096 reads per cell, took 32.29 seconds inside measurement windows (maximum 3.88 seconds/cell), and passed freshness and command accounting. Pilot timings are excluded from decisions. Freeze the runner before acquiring four blocks with forward/reverse policy ordering in equal proportions:

- Churn: 4,096 reads, three document sizes, two write mixes, two reads/write ratios and four paths: 192 cells.
- Controls: 2 KB documents, two write mixes, uncached/unrelated scenarios, 10/100 writes per second and three cache policies, eight seconds/cell: 96 cells.
- Warm hits: four blocks, three policies, three batches of 4,000 hits per read class: 576,000 hits.

Use the same isolated two-CPU, 4 GiB server throughout each suite; the larger limit accommodates the largest seeded data set without eviction pressure. Acquisition is expected to take approximately half an hour including setup and teardown. Run suites sequentially without competing validators. Record paired medians and all block directions. Actual saved reads plus repeatable latency/resource gains establish targeted usefulness. Added stream/routing costs without saved reads in uncached or unrelated controls block universal default adoption. If a decision depends on unstable CPU comparisons, repeat only those matched comparisons with longer windows and reversed ordering; disclose unresolved uncertainty rather than turning it into a negative result.

## Risks / Trade-offs

- Local single-member MongoDB and short windows limit generality and CPU precision. Report actual conditions and do not claim production capacity or statistical noninferiority.
- TCP bytes include protocol framing and polling, exclude TLS, compression and other clients, and differ from logical BSON. Keep the writer/read client outside the proxy so stream-only wire costs remain interpretable.
- Field dependencies require conservative handling of numeric equality, collation, paths, arrays, null/missing, replacement and query operators. A successful bounded projection does not establish a correct dependency extractor; document these admission gates without implementing one.
