# Design

## Context

See proposal.md for motivation. Existing tests provide a disposable MongoDB replica set, pytest-timeout and both facade implementations. Stream health is not a catch-up barrier; tests must observe event application.

## Goals / Non-Goals

Exercise production facades, routing, and recovery together without changing their API. Use one manager per case; independent managers, deployment-wide linearizability, and throughput thresholds are outside this correctness workload.

## Decisions

- Share an async orchestration helper between the two execution models. Sync facade calls run through worker threads; async calls use tasks. Keep client and database cleanup in fixtures/context managers, and propagate worker exceptions through task groups.
- Use four continuous readers, two hot identities, and eight cold identities. Background readers visit hot identities four times as often as each cold identity. Each cycle performs insert/update/replace/delete on every identity: 40 writes and 320 checkpoint reads per cycle. Two default deterministic cycles bound CI work. At the end of each ten-write CRUD phase, assert without waiting that all four reader tasks remain running and each has completed at least ten reads since that phase began. Keep readers unconstrained between these observations. Larger runs use a positive pytest cycle option and pytest's existing timeout flag.
- Instrument the existing route function in tests after its real invalidation completes. Track monotonically increasing document revisions, including deletion revisions; readers compare against the revision processed before starting. Exact checks occur while the writer holds the target stable. Count driver reads per target and read shape; after the first checkpoint batch, the second must perform no MongoDB reads, including for negative results. Comparing every read with an independent latest database read would incorrectly reject permitted in-flight and stream-lag behavior.
- Pause real database reads after their result arrives. Process a real external invalidation before releasing them. For recovery, use the existing integration-test injection boundary at database `watch()`: instrument returned streams to fail only when `lose_history()` arms injection, inject one lost-history response on the next watch call, then gate the successful watch call and disarm injection. Unarmed watch calls forward normally, including natural reopens. This exercises production recovery without destabilizing the MongoDB topology or waiting for oplog rollover.
- Reuse pytest-timeout's thread timer for hard process termination; its signal timer can leave deadlocked worker threads alive after interrupting the main test. Do not implement a custom watchdog.

## Resource Costs

Writes and checkpoint reads scale linearly with cycle count and identity count. Background readers use fixed worker cardinality and bounded cache keys. MongoDB round trips dominate test time; each write waits for applied invalidation before its exact checkpoint, while background reads continue. No production hot path changes or runtime performance claims are involved. Record measured default workload duration in the commit body.

## Risks / Trade-offs

- Scheduler timing can vary → force admission/recovery interleavings with explicit gates; keep the CRUD schedule deterministic while requiring progress from every reader.
- Negative results lack a stored version → track deletion revisions and verify exact absence, driver-free repeated reads, and later insertion at post-event checkpoints.
- A deadlocked sync worker cannot be cancelled safely by an async task → rely on pytest's process-level hard timeout and bounded driver/gate waits.
