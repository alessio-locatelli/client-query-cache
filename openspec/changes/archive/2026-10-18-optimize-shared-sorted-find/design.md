# Design

## Context

See [proposal.md](proposal.md) for motivation. The owner already stores complete cursor results in the arena, but publishes only identity entries. Public shared collection classes override research `find()` with native fallback. The v15 raw acquisition and profiles are unavailable; its committed findings are historical evidence, not independently verified samples.

## Decisions

Publish positive-limit find entries under an empty identity byte string and their exact discriminator. Portable identity encodings are nonempty BSON envelopes, so these keys cannot collide with identity reads. Publish against the assigned namespace epoch: the core's namespace generation also advances on ordinary writes and is not a metadata epoch.

Retain owner selection and capture on misses, including larger-limit family reuse. Local exact hits use the same metadata, incarnation, progress, availability and payload-copy validation as identity hits. Cursor completion, immutable capture and size limits remain authoritative. Unbounded results stay on owner selection. This avoids duplicating #258's miss work.

Maintain a set of published find payloads per namespace. A processed write removes those publications while preserving unrelated identity hits. Extend the observer's notification for uncanonicalizable identities so those writes also invalidate finds. Removal and eviction erase the set memberships. Invalidation costs O(published find entries); no additional allocation or traversal occurs on identity hot reads. Measure this write cost rather than claiming scalability beyond the bounded workload.

Alternatives:

- Faster RPCs retain an extra owner snapshot, transport copy and scheduling on every hit. They do not address the root cause; no further investigation is needed for this issue.
- A native namespace-generation field could invalidate all result publications in constant time, but changes the native layout and concurrency model. Its value depends on measured write cost; evaluate that cost in task 2.1 before choosing more machinery.
- Publishing all result sizes improves coverage but increases retention and cursor-policy obligations without answering the bounded sorted workload. Public method coverage belongs to #295; no additional investigation is needed here.

## Evidence boundary

Use a bounded exploratory comparison with the v15 workload and existing harness, including direct, independent and shared paths in both models. Record CPU, group PSS, request latency, IPC and write invalidation costs. Compare the identity path with the starting `main` revision separately. These measurements select an implementation decision; they do not repeat the full v15 promotion protocol or imply public promotion. Preserve negative outcomes and reproduction commands in the report.

## Risks

- Small result sets may not amortize an additional owner process and native index. Measure group memory including the owner.
- Publication keys may be unportable. Owner selection must retain the established bypass behavior.
- Admission can race writes or eviction. Keep publication under core authority and extend differential and real-cursor coverage.
