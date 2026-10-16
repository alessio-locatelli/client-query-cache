# Shared worker cache: classify default identity reads once

This study continues [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272) after [version 13's unstable hot comparison](../v13/results.md). The single `shared-index` candidate is the first clean commit containing this registration and the complete implementation below. Record its revision in every report; later implementation changes invalidate acceptance measurements.

## Candidate

Retain version 13's native relay, namespace contexts, integer wire envelopes and admission fences. Default shared `find_one` requests with an exact one-field dictionary, plain string `_id` key and built-in integer identity use one classification pass. Other filters, identity types, projections, explicit collations and keyword options retain the general path. Bound-session and read-profile inspection still runs for every request. Shape canonicalization, metadata eligibility, owner reattachment, codec normalization, native read-through, capture validation and admission use the existing authorities. Cached default collation still excludes shared reads.

This removes repeated identity extraction and general filter traversal for a known simple shape. No eligibility or public interface changes. Real sync/async reads cover bound sessions, incompatible read profiles and newly discovered collection collation, alongside existing invalidation, cancellation, transport-loss and codec tests.

## Frozen protocol

The [configuration](config.json) differs from v13 only in registration number. The [environment](environment.json), compiled native binary and observer policy are unchanged. Run fresh thirty-eight-window baseline-only qualification before candidate timing, starting at 1,006/1,000/319 requests/s. Retain v10's downward-only halving rule, three-attempt cap, sample-preserving durations, all health requirements and both manual checks. No candidate observation selects a rate.

Run the complete twelve-block cold phase first. Any failed or unstable required cold bound stops the study. A pass still requires fresh screening (six blocks), confirmation (twelve), capacity (three windows at every required point), active (twelve), sensitivity (three), and all seventy-five timed faults. Preserve every v9 inference setting, sample floor, balanced order, seed, draw count and leave-one-out check. Report sorted-find sensitivity separately; it cannot support general promotion.

Issue #272 requires cold P95 and P99 upper bounds no more than 1 ms above direct reads at four and eight workers in both execution models, with passing hot, active, capacity and timed-fault evidence. No historical phase substitutes for this candidate's evidence. Budget approximately eleven hours for qualification and performance acquisition, plus smoke, timed faults and analysis.

## Reproduce

Use the [v10 reproduction commands](../v10/registration.md#reproduce), replacing each `v10` configuration, qualification, output and analysis path with `v14`. Use the frozen native extension from v13, whose release-mode Loom models pass. The fault configuration stays at `reports/shared-worker-cache/v8/fault-config.json`. Keep raw outputs untracked, use fresh paths and inspect explicit analyzer verdicts and failures.
