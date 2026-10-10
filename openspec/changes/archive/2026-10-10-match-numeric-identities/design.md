# Design

## Context

See [proposal.md](proposal.md#why) for the defect and the [delta spec](specs/cache-core/spec.md) for the contract.

Identity reads and write routing both pass an identity through `order_sensitive_key` before canonicalizing it.

- **Reads.** An `_id` read first normalizes the identity through BSON encoding and decoding with the stream codec, so it has the Python types an event identity would have. A read whose raw `_id` value cannot be canonicalized bypasses the cache. For example, any value containing `bson.Decimal128` bypasses, because `Decimal128` is unhashable.
- **Writes.** `record_write` advances the namespace generation for every event. It advances an identity generation only when the event's `documentKey._id` can be canonicalized, and it skips that step silently otherwise.
- **Number types.** `int`, `Int64` and `float` already compare and hash as equal by value. A `Decimal128` event identity cannot reach the cached `int`, `Int64` or `float` identity that it equals on the server.

Probes against `mongo:8.0.4-noble` with PyMongo 4.18.2 showed the following:

- **The defect.** `find_one({"_id": 1})` matched and cached a document stored with `_id: Decimal128("1")`. After the manager processed an update to that document, the cached view still returned the old document.
- **Values the server treats as equal.** These pairs matched:
  - `_id: 1` and a stored decimal `1`;
  - `1E+1` and `10`;
  - `-0` and `0`;
  - decimal and double infinity;
  - decimal and double `0.5`;
  - an embedded `{"n": Decimal128("3")}` and `{"n": 3}`.
- **Values the server keeps apart.** The double `19.99` matched neither the decimal `19.99` nor its 34-digit rounding. `Int64(2**53 + 1)` did not match the double `2**53`.

Python's exact equality and hashing across `int`, `float` and `decimal.Decimal` agree with every probe.

## Goals / Non-Goals

**Goals:** Route every write to the identity that MongoDB considers equal to the written document's `_id`, without merging values that MongoDB keeps apart.

**Non-Goals:** Making reads with decimal filter values cacheable. Discriminator keys and facade eligibility checks are unchanged.

## Decisions

### D1. Canonicalize decimal identities by exact numeric value

The non-discriminator mode of `order_sensitive_key` converts `bson.Decimal128` to `decimal.Decimal` with `to_decimal()` at any nesting depth. Reads, write routing and unique-key alias values all pass through this helper, so both sides stay symmetric. `Decimal(1)`, `1`, `1.0` and `Int64(1)` then compare and hash as equal.

- **NaN values.** A quiet decimal NaN remains non-reflexive, and a signaling NaN remains unhashable, so neither can be canonicalized. No reflexive cached identity can equal them on the server either.
- **Discriminator mode.** It still distinguishes numeric subtypes and leaves `Decimal128` unhashable.
- **Cacheability.** The facades check canonicalizability on the raw read value and on the normalized identity, before this helper runs. Reads with decimal `_id` values therefore still bypass. Likewise, a unique-key resolution whose document has a decimal `_id` is still not admitted.

| Alternative                                                                                    | Pros                                        | Cons                                                                                                                                                     |
| ---------------------------------------------------------------------------------------------- | ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Exact decimal conversion (chosen)                                                              | Matches every server probe; O(1) per node   | Covers numeric equivalence only                                                                                                                          |
| Advance every identity generation in the namespace when an event identity is uncanonicalizable | Defends against unforeseen unhashable types | O(tracked identities) per such write; collections keyed by decimals would lose identity caching; misses identities that canonicalize but compare unequal |
| Round doubles to 34 digits before comparing                                                    | Mirrors one hypothesized server rule        | Contradicted by the probe: the server does not match the rounded decimal                                                                                 |

Unknowns: none. Read and event identities share BSON decoding, which already gives other server-equal types the same Python type. PyMongo, for example, decodes symbols as `str`. Numeric types are the remaining gap, and the probes cover it. Conclusion: adopt the exact conversion. No follow-up is needed.

## Risks / Trade-offs

- [The conversion runs on every routed write identity] → It adds one type check per identity node. Task 1.1 measures `record_write` routing before and after the change.
- [Numerically equal identities share one generation counter] → The server matches the same documents for equal values, so a write to either spelling must invalidate both.
