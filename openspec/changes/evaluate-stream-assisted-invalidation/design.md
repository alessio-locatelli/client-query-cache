# Design

## Context

See [proposal.md](proposal.md) for motivation. The existing simulator predicts invalidations; it does not account for projection, transport or decoding. The database stream also observes collections without resident entries.

## Decisions

Use the existing isolated replica set, seeded document-size profiles, dedicated clients, byte proxy and container CPU measurement. A standalone runner compares no stream, routing metadata, insert scalars, update names and full insert documents, with identical raw reads and writes. This isolates added stream cost without inventing a production guard or crediting an unimplemented hit-rate benefit. No images or event lookups are enabled.

The scalar experiment projects one fixed top-level `index` field. Numeric and Boolean values are bounded; strings qualify only through 64 UTF-8 bytes. Missing, null, arrays, objects and larger strings produce an explicit unknown outcome. The update experiment returns changed, removed and truncated-array names, never updated values; over 32 names or any name exceeding 64 UTF-8 bytes produces unknown. It preserves the distinction between known-empty and unknown. These bounds deliberately trade selectivity for predictable payload size. Unknown and non-applicable operations require collection invalidation in any subsequent design.

Full insert payloads provide a cost control: they require no lookup but scale with document size. They could route arbitrary partitions; their disadvantage is charging every insert, including unrelated collections. `updateLookup` and pre/post images have additional I/O or storage costs and are excluded by the issue. No further investigation of those alternatives is needed here.

### Acquisition and decision protocol

Before timing, exercise projection semantics against real MongoDB, including scalar boundaries, absent fields, large updates, removal, array truncation and replacement. The runner must drain and count every write event, fail visibly on consumer errors or timeout, and exclude stream establishment and teardown from timed windows.

Measure three counterbalanced blocks of the existing small/medium/large profiles. Each block includes idle and read-heavy (10 reads/write), balanced (1) and write-dominant (0.1) workloads at 10 and 100 writes/second, with writes either to the read collection or an uncached sibling. Active writes alternate inserts and updates; updates alternate a scalar increment and a document-sized string replacement. Windows last two seconds, with actual duration and achieved write rate recorded. Record server CPU, process CPU, logical BSON, and both wire directions. Reads are direct PyMongo on every path. Process CPU includes writers, readers, consumer and byte-proxy threads, so paired deltas approximate stream cost rather than isolating decoder CPU. No-stream controls establish absolute stream overhead; routing-only is the candidate baseline.

Register the decision before collecting results: recommend a production guard only with a measured end-to-end benefit and no reproducible regression in uncached or unrelated workloads. This transport study cannot satisfy the first condition. It may reject an expensive default or establish a bounded candidate's cost, but neither modeled cache hits nor a noisy CPU difference authorizes runtime changes. Record ranges and medians, avoid interpreting short-window CPU ratios as precise estimates, and retain the routing-only default unless later workload-specific evidence satisfies both conditions. Reopening conditions belong in the report, rather than an unowned implementation TODO.

An end-to-end guard prototype would establish net benefits but would design the subsystem before the issue's cost gate. It is therefore rejected for this evaluation. A simulator alone is cheap but cannot measure server or network costs. Task 1.2 resolves the remaining empirical projection-cost unknowns.

## Risks / Trade-offs

- Local single-member MongoDB and short windows limit generality and CPU precision. Report actual conditions and do not claim production capacity or statistical noninferiority.
- TCP bytes include protocol framing and polling, exclude TLS, compression and other clients, and differ from logical BSON. Keep the writer/read client outside the proxy so stream-only wire costs remain interpretable.
- Field dependencies require conservative handling of numeric equality, collation, paths, arrays, null/missing, replacement and query operators. A successful bounded projection does not establish a correct dependency extractor; document these admission gates without implementing one.
