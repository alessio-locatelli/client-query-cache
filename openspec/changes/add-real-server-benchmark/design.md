# Design

## Context

Every existing benchmark (`tests/benchmark/stream_cost/`) and integration/e2e tier runs against a `testcontainers`-managed, single-node local replica set (`tests/conftest.py::mongodb_uri`). None of that infrastructure reaches a real, network-attached deployment, so it can't be reused for connection setup here — this benchmark needs its own, separate fixture chain. See proposal.md for the motivating gap and for what changes.

## Non-Goals

- A general-purpose, manually dispatched benchmark runner or a versioned report format like `benchmarks/stream_cost` provides — this is a single pytest-driven comparison, not a report-producing tool, so it does not need its own CLI entry point or JSON schema.
- Measuring raw on-wire byte counts. A real SRV-resolved, TLS-encrypted Atlas connection has no local proxy point to intercept bytes the way `benchmarks/stream_cost/proxy.py` does for a `testcontainers` deployment. See Decisions.
- Covering the async API. The existing `tests/benchmark/stream_cost` fixtures only exercise the synchronous `CacheManager`, and nothing in the request asks for async coverage.

## Decisions

**Process model: two independent `multiprocessing.Process` workers, not threads or a single process.**
A single writer process holds a plain `pymongo.MongoClient` and repeatedly inserts/updates a small, fixed set of documents. A separate reader process holds its own client (or `CacheManager`, depending on phase) and repeatedly reads that same set. Separate OS processes with independent connections most directly model two independent application components sharing one database — the scenario the proposal asks the benchmark to imitate — and avoid any in-process contention or GIL interaction from masquerading as network latency. Worker bodies live as top-level functions in a plain module (not closures or fixtures) so they stay picklable under either the `fork` or `spawn` multiprocessing start method.

**Connection source: `.env` loaded by `uv run --env-file`, one variable, `REAL_MONGODB_URI`, read from `os.environ`.**
`justfile`'s `pytest` and `tests_and_coverage` recipes check whether `.env` exists at the repo root and, only then, add `--env-file .env` to the `uv run` invocation; `uv` then exports its contents into the pytest process's environment before it starts, so the fixture itself is a plain `os.environ.get("REAL_MONGODB_URI")` with no parsing of its own. This mirrors the single-URI shape of the existing `mongodb_uri` fixture (`tests/conftest.py`) so the reading/writing code in the benchmark can stay agnostic to where the URI came from, and avoids adding `python-dotenv` (or any other package) as a dependency purely to re-implement what `uv` already does for free.

**Skip strategy: two independent, explicit skip checks, not one.**

1. `GITHUB_ACTIONS` (or `CI`) set truthy → skip, regardless of whether a URI happens to be configured. This is a deliberate, defense-in-depth guarantee that this benchmark never attempts an external network call from CI, independent of whatever secrets a future workflow change might add — matching the existing `continuous-integration` capability's requirement that CI not depend on a shared external database.
2. `REAL_MONGODB_URI` unset/empty → skip. This is what makes the benchmark safe for every contributor who lacks the real cluster's credentials.

Both use `pytest.skip(reason=...)` with a distinct, human-readable reason so a contributor (or CI log reader) can immediately tell which condition applied.

**Resource-usage metric: PyMongo command-monitoring round-trip counts, not byte counts, filtered to `find` commands.**
Registering a `pymongo.monitoring.CommandListener` and counting `CommandStartedEvent`s per phase gives a deterministic count of server round trips using only public PyMongo API — no proxy, socket interception, or TLS termination needed, which a real Atlas connection does not offer a safe hook for. The counter only counts `find` commands, excluding the change stream's own background `getMore` polling and the one-time `hello`/`list_collections`/`list_indexes` probes: those are the concern of the existing `stream-cost-benchmarking` capability, and counting them here would add noise (a `getMore` poll fires on its own cadence regardless of how many reads this benchmark issues) unrelated to the thing this benchmark is meant to catch — an unexpected extra round trip per read, or the cache no longer avoiding server round-trips.

**Timing metric: wall-clock around the steady-state read loop only, excluding connection setup.**
Both the cached and uncached read phases run a short, discarded warmup (populates the cache; establishes the change stream and lets it start receiving events) before starting the timed window, so DNS/SRV resolution, TLS handshake, and cache/change-stream warmup latency — all of which are one-time, connection-related costs unrelated to the cache's steady-state benefit — don't pollute the measured comparison.

**Threshold tightness, per the two answered clarifying questions:**

- The cache-benefit ratio (cached ≥ 2x faster than uncached) is a same-run relative comparison and stays tight — it self-normalizes against whatever the shared cluster is doing at the moment, since both phases feel the same conditions.
- The absolute wall-clock ceiling per phase is the first recorded measurement multiplied by a fixed, documented safety margin (implementation records the exact factor next to the constant when the first measurement is taken), so ordinary shared-tier variance doesn't fail the benchmark for a non-regression reason.
- The uncached phase's `find`-command-count ceiling is the first recorded, exact count with no margin: every uncached read sends exactly one `find` command, with no cache to ever turn a read into zero commands, so this count cannot vary run to run absent a real behavior change.
- The cached phase's `find`-command-count ceiling is _not_ exact, even though the metric is otherwise deterministic: the concurrently running writer (see workload sizing below) occasionally invalidates a document between one read and the next, and how many of the phase's reads land on a just-invalidated document depends on scheduling/timing races between the writer's commit and the reader's change-stream notification. This ceiling therefore carries the same kind of small, documented margin as the wall-clock ceilings, for the same reason — discovered while implementing the reader worker, confirmed with the user rather than assumed.

**Workload sizing.**
A fixed, small document set (documents generated via `faker`/`make_fake_document`-style helpers per `test-value-conventions`, sized in the low hundreds of bytes each) and a combined write+read rate held well under the free tier's 100 ops/sec ceiling — leaving headroom for the fact that a shared cluster's _effective_ available throughput for this benchmark is less than the tier's nominal cap. Total collection size stays at a few dozen documents, far under the 512 MB storage limit. Exact document count, per-phase duration, and rate are implementation-time constants (see tasks.md) tuned during the first real run so the full benchmark — connection setup, warmup, both phases, teardown — fits inside the ~20 second budget.

## Risks / Trade-offs

- **Shared free-tier cluster variance could still cause a flaky failure.** → The cache-benefit ratio and the command-count ceiling are both insulated from cluster jitter (relative comparison; deterministic count). Only the absolute wall-clock ceiling is exposed to it, and it carries a documented margin for that reason.
- **Hard-coded thresholds go stale as the cluster's baseline performance drifts over months.** → This is an accepted, documented limitation (not solved by this change): if the benchmark starts failing for a contributor with no corresponding code change, the fix is to re-run once and update the recorded constants, exactly as the proposal's "measure and hard-code" instruction describes. The constants' origin and rationale live in this file and in the commits that recorded them, not as inline code comments (the project bans those).
- **Connecting to a real deployment is inherently slower and less deterministic than `testcontainers`.** → Handled by excluding connection/warmup latency from the measured window and by keeping the workload small enough that the two measured phases plus that fixed overhead comfortably fit the ~20 second budget.
- **Multiprocessing workers must be picklable.** → Worker bodies are top-level functions taking only plain-data arguments (URI string, document IDs, rate/duration constants), not closures over fixtures.

## Migration Plan

Purely additive (see proposal.md Impact for the changed files); nothing existing changes behavior when `.env` is absent, which is every contributor's and CI's default state. Rollback is deleting the new test directory, the `justfile` conditional, and the doc section; no data or schema migration is involved.
