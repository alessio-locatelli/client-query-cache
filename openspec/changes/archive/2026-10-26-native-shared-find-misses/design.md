# Design

## Context

See the proposal for motivation. Main already uses a Rust exact-key index, while Python recursively constructs tagged BSON key trees. A find needs the canonical family for owner selection and the family/limit discriminator for local lookup. They contain the same query. The current wire representation distinguishes integer types, canonical tags and codec identities.

## Goals / Non-Goals

The delta specs define the behavior contracts. This correction targets measured key preparation. Public query classification, cursor snapshots, policy, owner handles, invalidation and generic identity reads retain their existing paths. The rejected membership state and local-find admission protocol are removed, rather than carried as inactive alternatives.

## Decisions

### Rust encoding with one family traversal

Add a native encoder beside the existing PyO3 bindings. Construct its type and instance lazily through a factory on the first actual find encoding, so owners and identity-only workers do not initialize it. Keep the fixed small tag registry as a compact sequence. It walks canonical tuples, registered tags and common scalar types and writes the existing BSON key representation. For specialized scalar types, reuse the existing Python wire encoder and official BSON implementation; retain their exact representations and errors. Pass that codec with the encoding call, so native instances retain only immutable tag labels and cannot keep a Python module alive through a callback reference cycle. Native integer handling distinguishes exact Python integers from subclasses such as BSON Int64 and datetime-conversion enums. Use CPython's native stack guard across tuple recursion; Python 3.14 checks native stack space separately from its Python recursion limit.

Encode the family once and reuse its encoded value when forming the exact discriminator. The two byte strings must match the existing encoder byte for byte. The native writer implements only the tagged-key envelope and common scalar grammar from the [BSON specification](https://bsonspec.org/spec.html); it is not a new general-purpose BSON codec. No parser, query engine or dependency is added.

### Bounded paired keys and existing selection

The worker key cache retains the paired bytes by canonical family/limit under its existing entry and per-key retained-byte-size limits. Its private key is the direct pair for plain integers, without the canonical-sequence wrapper that is needed only for serialization. Specialized limit keys also include their type: plain integers and BSON Int64 compare equal but have different wire representations. The family occupies one ordinary entry, shared across limits; each exact key occupies one further entry. Oversized keys remain usable for the current call without retention. A hot find requires one cache lookup. A miss carries the already prepared family bytes in the existing family/limit request, so outgoing frame sizes and limit representations remain identical to main. The owner retains exact, covering and unlimited selection and authoritative capture. Workers without a local index use the existing single-family encoding, avoiding unnecessary preparation.

Merge local find lookup and miss message construction so the keys survive the local lookup without being recomputed. Remote cursor capture does not reconstruct metadata that its core ignores; the owner already owns that information. Keep the native index layout, allocator, generic lookup and identity admission code from main. Reuse namespace publication sets without constructing a disposable empty set on every admission.

### Alternatives

| Alternative                         | Benefit                                                                         | Cost or unknown                                                                                            | Decision                                            |
| ----------------------------------- | ------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| Rust paired key encoding            | Removes Python recursion and duplicate query traversal without new shared state | Byte compatibility and end-to-end benefit require tasks 1.1–3.2                                            | Selected by the user's Rust direction               |
| Python prepared-key request         | Removes one worker traversal                                                    | Retains Python recursion; larger envelope needs a size fallback                                            | Superseded; no further research required            |
| Native directories or family filter | Removes most miss-selection requests                                            | Rejected directory resource costs; filter retains unexplained identity-tail increases                      | Keep frozen negative evidence; no further tuning    |
| Full native cache or owner rewrite  | Could remove more Python work                                                   | Current attribution does not establish a benefit sufficient to justify the larger policy/lifecycle rewrite | No additional research required for this correction |

## Risks / Trade-offs

- A different byte representation could break equality or portability. Differential tests compare exact bytes with the existing encoder over real canonical keys and generated values, including specialized scalars, signed and Int64 limits, Unicode, large keys and errors.
- Retaining two keys could increase memory. Share the existing bounded entry budget and preserve the per-key retained-size bound; measure live group PSS.
- Python callbacks remain for specialized scalar types. Count actual native/fallback calls separately from timing; do not claim every scalar is encoded entirely in Rust.
- A local improvement may not improve the closed-loop workload. Follow the finite registered comparison; retain negative results and prevent promotion on an unexplained reproducible regression without explicit user approval. The [Rust comparison report](../../../../reports/shared-worker-cache/current-costs/rust-encoding.md) records the measured tradeoffs and approval.

## Migration Plan

Deploy matching owner and worker wheels under the existing lifecycle contract. Key bytes and the private protocol remain identical. Rollback installs the preceding wheel; no stored mapping or user data requires migration.
