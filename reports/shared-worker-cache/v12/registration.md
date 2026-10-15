# Shared worker cache: scalar paths and equivalent TCP relays

This study continues [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272) after [version 11 fails cold acceptance](../v11/results.md). The single `shared-index` candidate is the first clean commit containing this registration, the scalar fast paths and the relay correction below. Record its revision in every report. Later implementation changes invalidate its acceptance measurements.

## Candidate and observer

Retain [version 11's admission implementation](../v11/registration.md). Exact built-in scalar values bypass generic container traversal where their existing representation is unchanged. Plain signed 32-bit integer identities avoid BSON round trips only when read and stream codecs are the same object, their document class is `dict`, and no custom decoder is registered. Wider integers, `Int64`, subclasses, other identity types and distinct/custom codecs retain BSON normalization. Empty identity-filter remainders reuse one immutable mapping.

The byte-counting relay enables `TCP_NODELAY` on both TCP legs, matching PyMongo's direct connections. Its previous sockets used the OS Nagle default. Preserve all byte counters, fault controls, path scopes and relay threads. Freeze this policy in [environment.json](environment.json); historical registrations remain frozen and cannot qualify the changed observer. The [development diagnostics](development.md) are excluded from acceptance.

## Frozen protocol

The [configuration](config.json) differs from v11 only in registration number. Use the same compiled native binary. Fresh thirty-eight-window baseline-only qualification covers the scalar paths and relay policy before candidate timing. Starting rates are 1,006/1,000/319 requests/s; retain the downward-only halving rule, three-attempt cap, sample-preserving durations, every health requirement and both manual checks from [v10](../v10/registration.md#current-baseline-calibration). No candidate observation selects a rate.

Run all twelve cold blocks first. Any failed or unstable required bound stops the study. A pass still requires fresh screening (six blocks), confirmation (twelve), capacity (three windows at every required point), active (twelve), sensitivity (three), and all seventy-five timed faults. Preserve v9's inference settings, sample floors, balanced order, both seeds, bootstrap draws and leave-one-out checks. Report sorted-find sensitivity separately; it cannot support general promotion.

Issue #272 requires cold P95 and P99 upper bounds no more than 1 ms above direct reads at four and eight workers in both execution models, with passing hot, active, capacity and timed-fault evidence. No historical phase substitutes for this candidate's evidence. Budget approximately eleven hours for qualification and performance acquisition, plus smoke, timed faults and analysis.

## Reproduce

Use the [v10 reproduction commands](../v10/registration.md#reproduce), replacing each `v10` configuration, qualification, output and analysis path with `v12`. The fault configuration stays at `reports/shared-worker-cache/v8/fault-config.json`. Keep raw outputs untracked, use fresh paths, and inspect explicit analyzer verdicts and failures.
