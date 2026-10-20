# Design

## Context

Existing stress tests exercise stream disconnects and history loss for one
manager. Existing shared-cache fault scenarios test a separate owner protocol.
This change adds regression coverage for direct and independently cached
workers running in separate processes against disposable MongoDB instances.

The quantitative study did not establish an acceptable observer method. Its
recorded outcome and stop rule are in
[`reports/worker-fault-recovery/research-outcome.md`](../../../reports/worker-fault-recovery/research-outcome.md).
This PR does not implement or claim quantitative recovery measurements.

## Decisions

### Test harness

Use a small test-only process harness with the public direct and asynchronous
cache-manager read paths. Each worker has a control pipe for reads, snapshots,
fault injection and shutdown. The harness starts a replacement by killing the
old process and waiting for a newly started process to become ready. The tests
do not run a timed request schedule or replay a historical warmup workload.

Use the existing `FaultableProxy` for TCP connection loss. Inject the
MongoDB history-lost error (code 286) at an independent worker's real
change-stream reopening path so the manager's production recovery code clears
the cache; the test does not force server oplog rollover. Subsequent stream
opens and document reads use the real MongoDB instance. Use MongoDB's
`replSetStepDown` on a disposable three-member topology to cause a real
election. The three-member topology uses host networking and loopback member
addresses so both the test process and replica-set discovery can reach each
member.

### Regression cases

Run two real workers per applicable path:

- Connection loss: direct and independent workers lose their proxied TCP
  connections; both later read the updated revision. Independent workers also
  reopen their streams and process the write invalidation.
- Primary stepdown: direct and independent workers reconnect through a new
  primary and read the updated revision.
- History loss: independent workers encounter an unresumable stream open,
  clear cached entries, reopen a stream and read the current revision. This
  case does not apply to direct workers.
- Worker replacement: kill one worker and start a replacement on both paths;
  the replacement reads the current revision from MongoDB.

These assertions establish correctness and useful recovery behavior only.
Timeouts bound test execution; they are not recovery-time measurements.

## Scope boundaries

Keep the three-member topology and process controls only for these
container-backed tests. Remove the registration planner, per-request timelines,
recovery analysis, observer-overhead trials, registration-specific CLI modes,
and their synthetic tests. Keep existing steady-state and shared-cache
benchmark behavior unchanged.

Leave the quantitative study pending. Any future study needs a new registration
after a pilot validates its observer method; it must preserve V8's stop rule and
address the prior measurement review before collecting a full matrix. The
unfinished work remains in this active OpenSpec change.
