# Design

## Context

See [proposal.md](proposal.md) for motivation. Earlier key compaction already makes canonical subtrees reusable, but cursor preparation still constructs a final discriminator that lookup constructs again. Capture wraps each document in BSON, inflates that wrapper to extract a raw document, and finally encodes the raw documents as a list. Capture also obtains the entry-size limit through a full statistics snapshot.

## Goals / Non-Goals

The existing cursor, codec, complete-consumption, bounded-storage, family-collision, and admission-race contracts remain authoritative. Collection-wide invalidation and shared-worker query eligibility are unchanged.

## Decisions

1. Represent an eligible find execution with a prepared shape containing its canonical family and final discriminator. Preparation happens after request, filter, and projection checks. Lookup accepts raw shapes for internal callers and prepares those at its boundary. Admission receives the prepared discriminator; source metadata reuses its family. Source hashing stays on the miss path to avoid adding warm-hit work. Keeping separate wrappers in cursor and lookup is simpler locally but repeats work. A global query cache would retain arbitrary caller inputs and require another eviction policy; execution-local reuse needs neither. No research beyond the measurements in task 1.1 is necessary.
2. Encode each captured document inside the existing value envelope with the official BSON encoder, then slice out the embedded BSON and retain a `RawBSONDocument` over those bytes. The codec owns the fixed envelope offset so capture does not duplicate its layout. Top-level BSON encoding promotes `_id` to the first field; embedded encoding preserves the native document order, including aggregation results. Final list encoding copies raw bytes without replaying application codecs. Slicing removes wrapper inflation while retaining snapshots before caller mutation and preserving field order. Retained-byte accounting measures the actual raw document payload; final admission still enforces the exact list envelope size. Hand-assembling BSON arrays could save another copy but would introduce a second serializer and custom format maintenance without measured need. Deferring all encoding until exhaustion would violate snapshot isolation. Task 1.1 resolves the size of the capture-encoding benefit; no separate investigation is needed.
3. Read the immutable entry-size limit directly from the core's existing LRU configuration rather than collecting unrelated counters. Expose the same internal accessor on the remote capture core and remove its obsolete snapshot shim. Copying the limit into each public collection or configuration object would add competing ownership. No further research is needed.

The execution remains: final-input preparation, local exact/family lookup, one native find plus caller-driven getMore on a miss, linear BSON snapshot work in returned bytes, then the existing guarded admission. Preparation is linear in query size once; capture retains at most the maximum-entry payload. These changes add no database I/O or new synchronization.

## Risks / Trade-offs

- BSON codec behavior must match ordinary cache encoding, including raw documents, UUIDs, ordered mappings, custom decoders, and failed custom encoders. Existing round-trip and mutation tests cover these cases.
- Removing wrapper bytes changes the internal capture cutoff, but both retained payload and final resident entry remain bounded by the same configured limit. Boundary tests must use actual retained BSON sizes.
- Local latency is noisy and does not predict production speedups. Compare repeated isolated cold, exact, and compatible reads with the same data and runtime, alongside the original churn workload. Record CPU, wall time, command counts, and separate profiles in the existing research report.
