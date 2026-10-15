# Design

## Context

See `proposal.md` for motivation. The existing native index and Python owner already have fencing and fault tests. Research acceptance for general workloads is incomplete; the public contract is deliberately independent of sorted-find research and cold-tail targets.

## Goals / Non-Goals

The contract lives in `specs/shared-worker-cache/spec.md`. This change does not rewrite admission policy in Rust or share values between hosts.

## Decisions

### Reuse the owner and index in the installed library

Move transport, publication and adapters under `client_query_cache._shared`; research imports those components. Public managers expose only identity reads. Keeping production imports under `benchmarks` would make wheels incomplete; copying the implementation would duplicate correctness fixes. Neither alternative needs further research.

### Explicit parent-owned process

`SharedCacheServer` starts a spawned owner and returns a picklable `SharedCacheConnection`. Workers construct their own PyMongo clients and attach through sync/async `SharedCacheManager`. A private runtime directory, random capability and Unix peer credentials restrict attachment to one trusted application identity. No capability appears in repr or logs. The connection grants access to all configured databases and must not cross tenant or credential boundaries.

Spawn avoids inherited clients, locks and event loops. Transparent owner election would add split-brain and shutdown ambiguity. An external daemon would require credential transport and independent supervision. Neither is necessary for the supported parent/worker deployment. Parent pipe loss shuts down the owner; bounded close escalates to terminate/kill and reaps it. Explicit restart preserves endpoint credentials but creates fresh shared memory; workers reconnect and discard metadata. Inherited managers and servers reject use; each worker creates its own resources after fork.

Replacement workers may start during owner loss. Public managers retain a disconnected endpoint and serve direct reads until transport recovery permits a local mapping. Metadata and slots are cleared when that first mapping attaches. Requiring initial owner availability would prevent worker replacement; masking all attachment errors would hide credential and deployment mistakes. The owner therefore sends explicit credential rejection without descriptors, while only temporary transport failures allow degraded startup. Permission and protocol errors remain visible. No separate availability mechanism or follow-up research is needed.

### Preserve fail-closed validity

Retain core-capture-before-native-validation ordering and availability/progress locking. Read-only sealed mappings, owner incarnation, namespace generation and progress expiry fence hits and admission. A silent stall can serve a previously published value until the configured progress deadline; change streams remain eventual, without read-your-writes guarantees. Tightening this to linearizability requires a different upstream barrier and is not part of this contract.

### Stable collection names

The supported database workload uses a fixed collection-name set. Index namespace capacity is distinct from Python generation/metadata retention, which can grow under name churn. Reclaiming generations without fencing old captures risks accepting an earlier admission into a recreated state. Requiring stable names gives a predictable initial contract without weakening those fences; bounded churn support belongs to [optional issue #282](https://github.com/alessio-locatelli/client-query-cache/issues/282). No churn implementation is necessary for this release.

### Validate capacities and reuse pure key encodings

Public configuration checks the native power-of-two slot rule, 32-bit arena-word and namespace bounds, and a slot limit that fits signed address-space sizing before starting a child. A worker needs both control and request connections, so capacity starts at two. Python annotations expose these bounds; runtime checks remain authoritative.

Cached collection views construct their immutable namespace identifier once and reuse it for all reads. Workers retain at most 8,192 pure key encodings. This covers the measured 4,096-identity hot set plus read shapes without duplicating document values. The former 256-entry bound cleared before an equivalent hot read could reuse its encoding. Larger bounded key retention costs worker memory, which the PSS measurements include. Eviction can repeat encoding work; it never changes validity or caches decoded documents. No follow-up research is needed for this choice.

Only keys encoded in at most 4 KiB enter either direction of the key cache. A count limit alone would retain gigabytes for large identifiers. The threshold bounds retained key size without recursive Python-object sizing or accounting on cache hits; larger keys are encoded/decoded for the current operation and discarded. A byte-budgeted eviction policy would add bookkeeping without improving the measured small-key working set. No research is needed for this admission limit.

### One installable distribution

Maturin builds the Python package and private Rust module together. Version 0.8.0 provides CPython 3.14+ ABI3 Linux x86-64 glibc wheels and an sdist containing locked Rust sources. Release builds use manylinux_2_28, and installed-artifact verification imports and starts the native owner outside the checkout. A separate extension distribution would require a second PyPI project and coordinated publication; shipping only source would require compilers in application images. Neither is needed. Other platforms and free-threaded interpreters are outside the initial supported package build contract; documentation and metadata state this explicitly.

### Costs and acceptance evidence

| Path                  | Work and scaling                                                                                                        |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Warm identity hit     | Local key preparation, expected constant-time index probe, O(document bytes) copy/decode; no socket or MongoDB call.    |
| Eligible miss         | Local capture, one MongoDB read and bounded one-way admission; no owner selection round trip after metadata activation. |
| First collection read | Metadata exchange plus collection probe and asynchronous stream activation.                                             |
| Invalidation          | One owner stream per database, publication proportional to affected cached shapes.                                      |
| Worker attachment     | One read-only index mapping and bounded session queues; mappings share physical pages.                                  |

The cache budget bounds accounted owner entries; the arena, index and per-connection queues have separate explicit limits. Total RSS also includes Python/PyMongo and transient frames. Publication may refuse a value before the accounted budget fills; refusal is an ordinary miss.

Measure installed public sync and async reads against direct PyMongo using real MongoDB, four workers, repeated hot/cold windows and mutation checks. Record latency, CPU, memory and native hit/admission counts. The release must demonstrate useful hot-read improvement and stream deduplication, not meet unrelated research promotion gates. Cold costs and the observed limiting path must be reported. Keep raw outputs untracked.

## Risks / Trade-offs

- A capability holder can read or poison this application's shared cache → trust all workers equally and never share a server between security principals.
- Owner outages add a bounded retry/IPC cost before direct-read fallback → preserve cooldown and document the progress-expiry bound.
- Native distribution narrows the tested platform contract → ship a compiler-free wheel for the supported platform and verify the source build separately.

## Migration Plan

Opt in by starting a server in the application parent before launching workers; pass only its connection to workers. Revert to the existing process-local manager to remove shared ownership. No persisted data migration is required. The maintainer creates the release tag and publishes after reviewing delivery evidence; the parent issue stays open until release readiness is established.
