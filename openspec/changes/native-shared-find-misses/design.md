# Design

## Context

See [proposal.md](proposal.md) for motivation. `ReaderIndex.lookup` already copies
and validates owner-published bytes; `capture` records namespace mutation,
database fence and time. The owner's local identity admission captures core
state **before** validating this token, so a later write is rejected by the core.
Find misses currently use owner handles and a second serialized query family.

The existing native exact-key table has 64-byte slots and a bounded arena.
`CacheEntry.find_source` identifies reusable positive-limit and unlimited find
results. Negative limits retain exact-only behavior and are outside the new
miss path. Namespace scalar methods retain their current selection path.

## Goals / Non-Goals

The contracts are in the delta specs. This design retains one stream owner and
the core's admission/eviction authority. It does not move invalidation policy,
MongoDB reads or BSON decoding into Rust, change public settings, or alter
process-local caching. Selective invalidation remains under
[#339](https://github.com/alessio-locatelli/client-query-cache/issues/339);
metadata budget changes remain under
[#337](https://github.com/alessio-locatelli/client-query-cache/issues/337).

## Decisions

### Exact table plus versioned family directories

Keep the existing exact lookup algorithm for identity and scalar entries.
Represent native find entries using a reserved non-BSON identity domain,
nonnegative limit and the encoded canonical family. Use distinct domain keys
for versioned family directories. Neither can alias encoded MongoDB identities
or existing namespace entries; full key equality remains mandatory after hash
matching. Do not enlarge the 64-byte slot or change the generic lookup loop.

Each directory contains sorted positive limits followed by unlimited zero, in a
fixed-width native encoding. It references existing exact find entries by limit,
not a second copy of their BSON. A reader tries the exact entry first, then
binary-searches a directory for the smallest covering positive limit, followed
by unlimited. A removed candidate is skipped or causes owner fallback; it
cannot turn into an unchecked payload reference. The selected payload uses the
existing copy/version validation and alone emits a recency token.

The native writer maintains directories as find entries are published and
removed. It reuses directory storage while capacity fits, marking the slot
version unstable before changing any payload word and stable only after its
length and contents agree. Geometric growth/shrink avoids reallocating and
rehashing an unchanged family on every mutation. Directory snapshots occupy the existing arena and table capacity;
writer bookkeeping is bounded by published find entries. Empty families release
their directory and bookkeeping. Invalidating a namespace removes both find
entries and directories before their storage is reused. Bump the mapping layout
version because the namespace validity header gains completeness state.

Alternatives:

| Alternative                                            | Benefits                                                | Costs and unknowns                                                                                                       | Decision                                                                   |
| ------------------------------------------------------ | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| Hash all limits of a family to the same cluster        | No secondary directory                                  | Exact hits become linear in family variants and can lengthen unrelated probe chains                                      | Reject on scaling grounds; no additional investigation needed              |
| Replace the complete cache with a native ordered store | One implementation for selection and eviction           | Requires moving codecs, policy, metadata and capture authority; current profiles do not establish their replacement cost | Reject for this measured boundary; no implementation or follow-up required |
| Keep owner selection and reuse the exact wire key      | Removes one serialization with little extra state       | Retains one synchronous selection exchange per miss                                                                      | Viable narrower option, superseded by the user's selected native direction |
| Independent workers or direct reads                    | Already measured alternatives; avoid shared control IPC | Duplicate cached results/streams or repeatedly execute MongoDB reads                                                     | Retain as workload choices and controls; no implementation needed          |

Directory allocation, hash lookup and maintenance costs remain unmeasured.
Tasks 1.1 and 3.1 establish their floors and end-to-end value; no benefit is
claimed until those measurements pass.

### Native absence needs publication completeness

A missing native key is insufficient when the authoritative core retained a
value that could not be published. Add bounded completeness state per namespace
with separate owner/core and native-directory contributions. Both must be
complete before absence authorizes local capture.

The publisher tracks references to unpublishable reusable find entries, without
copying their query trees. Removal, replacement, invalidation and namespace
release remove these references. This set is bounded by live core entries;
generation changes discard stale membership. The native writer similarly
accounts for missing directories within its published-entry bound. Allocation
failure preserves usable exact entries and marks completeness false; it must
not leave an unchecked directory. Restore completeness only after all relevant
failures have been removed or repaired. Capacity tests cover both contributions.

An alternative is to treat every native absence as a miss. It avoids this state
but loses compatible results retained only by the owner. Reject it; no further
research is needed. Duplicating payloads in an independent directory would
increase arena demand and reclamation complexity without helping selection;
reject that option as well.

### One preparation and one-way local admission

Add a reader operation that accepts the encoded family and limit once. It
returns validated bytes, a local capture token on complete absence, or an owner
fallback indication. Eligibility, metadata, attachment incarnation and liveness
checks stay in the adapters. Unsupported limits/keys retain the existing path.

A local miss uses native MongoDB cursor batching and the existing immutable
document capture. Complete consumption queues an admission with namespace,
family, limit, slot, epoch, incarnation, token and encoded result. Partial close,
error or cancellation clears worker snapshots and has no owner handle to
release. Reuse the existing bounded native queue and socket fallback, including
its frame reuse and recovery behavior. Do not compute owner-derived source
metadata or prepare an unused second wire key in the worker.

The owner validates authenticated fields and slot assignment, captures a core
namespace generation, then validates the native token while holding progress
and availability exclusion. It admits through `admit_namespace_encoded` using
the decoded family/limit. Core generation checks remain authoritative if a write
occurs after token validation. Reversing this ordering could admit a stale read.

Worker-writable result mappings would remove a payload copy, but violate the
read-only publication boundary and require a different security design. Reject
that alternative; no further work is needed under this issue.

## Risks / Trade-offs

- Extra directory slots/bytes reduce publication capacity. Both tables remain
  bounded and saturation retains owner reuse; task 3.1 measures footprint and
  admission behavior, rather than promising a net memory saving.
- Updating a directory costs work proportional to that family's limits. Reuse
  the writer's sorted membership instead of rewalking unrelated entries; measure
  1, 8 and 64 variants in task 1.1. Do not accept a demonstrated regression.
- Readers can overlap directory replacement or payload reclamation. Validate
  each copied directory and the selected exact payload independently; Loom and
  operation-order tests must reject torn, removed and foreign values.
- Publication failure has two sources. Tests must demonstrate that repairing one
  cannot incorrectly clear the other's incomplete state, including slot reuse.
- The historical blanket miss-study requirement conflicts with #341's explicit
  bounded investigation. The benchmarking delta scopes new evidence to affected
  paths and preserves the earlier acquisition as historical evidence.

## Migration Plan

Owner and workers use one installed library/native build. New mappings reject
the previous layout, with no migration or mixed-layout fallback. Deployment and
rollback restart the owner and workers; cached values are disposable. Public
configuration and stored MongoDB documents need no migration.
