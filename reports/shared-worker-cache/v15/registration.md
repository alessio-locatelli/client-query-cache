# Shared worker cache: admit through the control queue directly

This study continues [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272) after [version 14's failed cold study](../v14/results.md). The single `shared-index` candidate is the first clean commit containing this registration and the complete implementation below. Record its revision in every report; later implementation changes invalidate acceptance measurements.

## Candidate

Retain version 14's scalar classification, native relay, namespace contexts, integer wire envelopes and admission fences. Native-queue capability belongs to the authenticated control attachment and is immutable for that mapping. A valid local miss can capture and enqueue through it without opening a data socket or requesting an owner capture. Both adapter models try the native queue before data-channel transport. Closed endpoints drop admissions; detached readers remain unable to capture or enqueue. A full queue reuses the same encoded frame for bounded socket fallback. Socket-only attachments retain reconnection and owner-selection behavior.

Each collection view also retains its portable default wire shape beyond eviction of unrelated identity keys. Other shapes retain the existing key cache. Canonicalization and codec eligibility remain authoritative, including codecs with unhashable metadata; BSON identities outside the wire type set retain native fallback.

The observer model is unchanged. The [environment](environment.json) freezes the rebuilt extension, including its queue-capability getter. [Development diagnostics](development.md) are excluded from acceptance.

## Frozen protocol

The [configuration](config.json) differs from v14 only in registration number. Run fresh thirty-eight-window baseline-only qualification before candidate timing, starting at 1,006/1,000/319 requests/s. Retain v10's downward-only halving rule, three-attempt cap, sample-preserving durations, all health requirements and both manual checks. No candidate observation selects a rate.

Run the complete twelve-block cold phase first. Any failed or unstable required cold bound stops the study. A pass still requires fresh screening (six blocks), confirmation (twelve), capacity (three windows at every required point), active (twelve), sensitivity (three), and all seventy-five timed faults. Preserve every v9 inference setting, sample floor, balanced order, seed, draw count and leave-one-out check. Report sorted-find sensitivity separately; it cannot support general promotion.

Issue #272 requires cold P95 and P99 upper bounds no more than 1 ms above direct reads at four and eight workers in both execution models, with passing hot, active, capacity and timed-fault evidence. No historical phase substitutes for this candidate's evidence. Budget approximately eleven hours for qualification and performance acquisition, plus smoke, timed faults and analysis.

## Reproduce

Use the [v10 reproduction commands](../v10/registration.md#reproduce), replacing each `v10` configuration, qualification, output and analysis path with `v15`. Build the optimized native extension at this candidate before qualification. The fault configuration stays at `reports/shared-worker-cache/v8/fault-config.json`. Keep raw outputs untracked, use fresh paths and inspect explicit analyzer verdicts and failures.
