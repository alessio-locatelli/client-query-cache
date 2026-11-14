# Native migration constraints and measurements

The November 2026 migration moved capture accumulation, key preparation and
shared ownership into Rust. Current mechanisms live in the
[architecture guide](../../docs/development/architecture.md) and
[shared-cache reference](../../docs/development/shared-cache.md).
This record preserves measured boundaries useful when considering further work.

## Method and sources

Baseline M was `c931b679ce612dde46246329ea430d4d847c396f` (0.10.0);
combined F was `c02c7f27e76ee7bd100ad2aff932355472c58459`, with final entry-layout
correction F2 at `ed92c9c205e385bb6429e65f6eda0eb17e76942d`.
Measurements used installed, unprofiled release wheels, CPython 3.14.7,
Linux 7.2.13/glibc 2.43 and the Intel i3-13100 host. MongoDB 9.0.4 ran in a
separate two-CPU/1-GiB disposable container. M used PyMongo 4.18.3; F used
4.19.0, so combined differences include that dependency update. Direct controls
had median CPU changes from −2.9% to +0.7%.

Each component used three counterbalanced predecessor/candidate blocks with
validated results, cache outcomes and resolved CPU counters. Public cells used
four spawned workers, one serial caller per worker and majority reads. Profiles
were separate. Five combined blocks alternated M/F and F/M; requests within a
window were not independent replications. Group CPU includes workers, owner
and read supervision, excluding MongoDB, builds and initialization.

## Component decisions

| Component and target                                           | Measured result                                                                   | Maintenance implication                                                                      |
| -------------------------------------------------------------- | --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Encoded capture: cold `find`, 4,000 × 1,024-byte documents     | Median complete-read CPU −25.4% sync, −21.1% async in component pairs             | Avoid encoding each snapshot again at finalization; preserve codec and entry-size semantics. |
| Key preparation: hot `find_one`, 256-element `$in`, 1,024 keys | CPU −60.5% sync, −52.1% async in component pairs                                  | Traversal and Python type checks can dominate small-result reads.                            |
| Shared owner: 4,096 drained cold identity admissions           | Owner CPU 38.4–44.9 → 20.7–24.2 µs/read; group CPU median −9.8% sync, −8.3% async | Account for drained admission work, not just foreground latency.                             |
| Facade dispatch: hot 16-document `find`                        | Component CPU medians −32.4%/−30.6% local and −22.8%/−29.9% shared, sync/async    | Repeated signature binding and codec-key construction mattered outside native lookup.        |

These are historical workload effects, not current speed guarantees. Short
identity controls were bimodal and had adverse initial signals; larger matched
rechecks did not reproduce those signals. Cold tails remained variable.

The combined campaign measured hot generic `find_one` CPU reductions of about
43–51% across models/storage paths, and hot 16-document `find` reductions of
17–34%. Cold identity reads showed no resolved effect. F initially added about
1.8 MiB at 64,001 small entries: every local entry could hold an unused shared
arena descriptor. F2 moved those blocks into shared residency, restoring equal
or lower warm memory than M. The [memory report](../process-memory/summary.md#native-core-residency)
owns the residency figures and close/allocator limitations.

## Boundaries retained in Python

A complete 20,000-event manager workload used 696 µs process CPU per processed
event, while routing one event including native invalidation telemetry cost
2.24 µs. Routing was about 0.3% of that complete cost; a native router rewrite
had no demonstrated benefit. This observation predates opt-in telemetry.

After the native owner transition, a separate py-spy run attached before three
256-cold-read-per-worker repetitions. Queued-frame/key decoding had no sampled
Python cost above 0.2 µs/read. Framing and dispatch stayed in Python; lack of
samples is a resolution limit, not proof of zero cost.

Local `find_one` could reuse metadata returned by its eligibility check. Shared
metadata lookups re-check expiry at different decision points; collapsing them
would move when refreshed metadata applies and needs a consistency argument.
Python fallback remains necessary for custom key/container forms and driver
integration. Tests of plain native paths alone cannot qualify its removal.

## Reproduce

The frozen acquisition module is `research.native_local_integration.acquire` at
the final harness revision `9c08dc15` for M/F. Build each source's release wheel
in a separate checkout, install it into its own locked environment, and run the
same harness with each installed interpreter. The
[historical acquisition registration](https://github.com/alessio-locatelli/client-query-cache/blob/243cbfb790766e9ee25b3ecced1ffe83e96d083c/reports/native-internals/plan.md)
contains the component cell definitions and complete commands. It distinguishes
candidate sources and F2's narrower recheck; do not attribute F's whole campaign
to F2. Raw outputs are untracked; fresh acquisitions reproduce the method,
not the exact historical layouts or numbers.
