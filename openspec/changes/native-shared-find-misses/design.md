# Design

## Context

See proposal.md for motivation and the report for the rejected directory
candidate's measurements. The replacement removes compatible-limit directories
and retains the owner's compatible-result authority. A native miss decision
needs only evidence that no reusable family member can exist; it does not need
to enumerate that family's limits.

## Goals / Non-Goals

The delta specs define the contracts. This design keeps native exact hits and
local miss capture, with bounded authoritative owner admission. It does not move
cache policy, result decoding, metadata or invalidation semantics into Rust.
Process-local metadata and selective invalidation remain under issues #337 and
#339. It introduces no public option or dependency.

## Decisions

### Exact hash lookup plus a bounded counting family filter

Retain the generic 64-byte exact-key slot and lookup algorithm. Find exact keys
use the encoded canonical family and nonnegative limit in the existing reserved
non-BSON identity domain. No second family slot, directory payload, BTreeMap or
per-family writer map is maintained.

Add one global counting filter whose cell count equals the configured native
slot count. Each cell is one atomic word. Hash the namespace slot, epoch and
encoded family; use two derived cell indices. If both indices are equal, update
that cell once. A published find contributes one count to each cell. Store its
filter hash in the existing allocation bookkeeping, using a tagged field that
cannot confuse hash zero with an ordinary payload. Its lifetime is the payload's
publication lifetime, not the Python Payload object's lifetime.

Validate capacity and allocate key storage before incrementing; increment
before making the exact publication visible. Refusal leaves counts unchanged. Remove counts only after the exact publication is no longer visible.
Re-publication and replacement must not double count; unpublish clears the
allocation's membership, and later release is a no-op for the filter. Counters
cannot overflow because live contributions are bounded by the native published
slot limit. Publication failures retained by the core still make the namespace
incomplete through the existing bounded unpublished-entry accounting.

After an exact miss, a reader checks native liveness/epoch and namespace
completeness. If either filter cell is zero, no published member of that family
can exist, so it returns the existing local capture token. Otherwise it returns
owner fallback. Collisions and hash equality can only add fallback requests;
filter membership never authorizes a hit or hides an unpublished core entry.
The owner retains exact/covering/unlimited selection under its existing policy.
A concurrent insertion may precede or follow a reader's absent observation; a
concurrent removal cannot produce false absence for any other live contributor.
Token validation and core generation fencing remain authoritative at admission.

The filter uses 8 bytes per slot (128 KiB for the measured 16,384 slots), and reuses the native allocator's free-list word while an allocation is live; it adds no allocation-metadata word. Only touched pages become resident.
It is shared across namespaces so large configured namespace limits do not
multiply its allocation. Epoch participates in the family hash; removal/reset
must balance every contribution before namespace-slot reuse. Bump the native
layout version. Neither filter saturation nor collisions affect correctness;
they reduce the proportion of misses avoiding owner selection. Task 1.1 measures
this scaling at fixed capacity and verifies balance after eviction and reset.

### Socket admission for locally captured finds

Preserve the current local miss envelope and admission fences, but send completed
find results through the existing bounded socket transport. Exact identity
admissions retain their existing native-queue path. This avoids making previously
untouched per-worker admission queues resident just because find misses changed.
Reuse encoded frames and existing send deadlines, capacity and recovery rules;
do not add a transport or initialize additional per-worker resources. A local
find miss requires a connected leased socket. If disconnected, fall back to
owner selection, which performs the existing reconnect/recovery path. A socket
that disconnects during admission retains the existing bounded-send/drop
behavior; the next miss detects disconnection and attempts owner recovery.
Exact local hits continue without a socket. Cover both disconnect boundaries
in sync/async tests so local misses cannot loop forever without reconnecting.

The worker prepares the family once and reuses it for exact lookup, filter
lookup, local admission or owner selection. Native selection hashes the family
once and derives the exact-limit hash and filter indices from that result;
it must not traverse the family twice to maintain the filter. A filter collision must not trigger
a second query traversal. Partial close/error/cancellation clears snapshots and
needs no owner discard handle. The owner captures the core namespace generation
before validating the native token under progress/availability exclusion; the
core generation check rejects a write after token validation.

### Alternatives

| Alternative                                                 | Benefits                                                                                                 | Costs / unknowns                                                                                                                          | Decision                                                                    |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| Native compatible-limit directories                         | Local exact and covering hits                                                                            | Rejected candidate adds 4.41–6.44 MiB group PSS and about 1.2 µs per native publication/removal entry; some memory is transport residency | Rejected by the user; preserve measurements, no further directory tuning    |
| Counting family filter with owner compatible selection      | Constant bounded membership updates; no family allocation/rebuild; native exact hits and definite misses | False positives add owner requests; performance and resource benefit require measurement                                                  | Approved replacement; tasks 1.1–3.2 cover unknowns before acceptance        |
| Reuse the prepared key but keep selection RPC on every miss | Small change; no new membership state                                                                    | Retains the cold selection boundary identified by profiling                                                                               | Viable fallback if replacement fails; no implementation without user choice |
| Native full cache or inline family tree                     | Could consolidate ownership and lookup                                                                   | Requires a wider policy/storage rewrite; current measurements do not establish its costs                                                  | Reject for this boundary; no additional research required                   |
| Native queue admission for local finds                      | Existing fast queue transport                                                                            | Touches up to four 1.06 MiB queues in this workload; resource tradeoff was rejected                                                       | Use existing socket path; remeasurement is required by task 3.1             |

## Risks / Trade-offs

- A saturated filter can send most misses to the owner. Measure actual selection
  counts and retain that limitation; never resize it invisibly or discard live
  counts to improve timing.
- Publication/removal order must prevent a false negative. Test duplicate
  publication, replacement, collisions, refused publication, unpublish/release,
  invalidation and namespace reuse; model the atomic ordering with Loom.
- The filter has a finite memory cost. Compare live
  group PSS and native mutation floors against main; no reproducible regression
  is acceptable without explicit approval.
- Socket admission may cost more CPU than native queue admission. Compare both
  total reader CPU and owner requests against main, retain rejected-candidate
  evidence, and stop if the revised design fails its registered requirements.

## Migration Plan

Build a version-matched owner and workers together. A layout mismatch retains the
existing attachment rejection; no persisted mapping or user data is migrated.
Rollback deploys the previous wheel to the whole group. The evidence plan uses
clean installed wheels and retains rejected measurements without claiming they
qualify the replacement.
