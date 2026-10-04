# Design

## Context

See [proposal.md](proposal.md). All six reads in each cached collection use the shared request classifier before lookup and admission. PyMongo 4.18.1 and 4.18.2 resolve `bind()` through the client's private `_get_bound_session()` method; no public accessor exposes the current context.

## Goals / Non-Goals

**Goals:** Classify effective sessions consistently in both execution models, bypass all cache activity for bound reads, and retain native argument validation and session precedence.

**Non-Goals:** Session-scoped caching, intercepting session lifecycle, monkeypatching clients, adapter prototypes, or changing native session semantics.

## Decisions

### Resolve effective session context at the shared classifier

Supply the original client's bound-session resolver to `request_bypass_reason` as a feature-detected capability. Explicit non-`None` sessions bypass without resolving a bound context, matching native precedence. An omitted session or explicit `None` consults the native resolver. A bound result selects the existing session bypass reason. This avoids importing driver context variables or maintaining a second context manager and keeps the two collection call sites mechanical.

### Let the native operation determine errors

The resolver raises `InvalidOperation` when a different client's session is bound. Classify that context as session-ineligible, then invoke the original read unchanged rather than raising from the classifier. Native methods can validate arguments before checking the session, and `estimated_document_count` does not support sessions. Direct delegation preserves that error order. Ended-session checks also remain native. Exercise both the resolver exception and malformed-input precedence over a warm entry.

### Keep the private dependency explicit

Feature-detect the resolver before classifying reads. A missing or non-callable capability selects session bypass for every cached read; no warm entry is served and no result is admitted. This permits native execution when a future driver removes the private method. If a callable resolver raises an ordinary exception, select the same bypass. Catch only around private inspection; native reads remain outside that handler, and cancellation or process-control exceptions propagate. Explicit sessions avoid invoking the resolver. Exercise the declared minimum and locked releases; this fallback does not certify future resolver semantics.

### Measure the added guard cost

The unbound path adds a bound-method allocation and one constant-time context lookup; explicit-session bypass avoids the lookup. No additional network operation is expected. Before and after the edit, time and profile the actual collection request guard on a disconnected caller-owned client for unbound, bound, and explicit-session contexts. Keep raw measurements under `/tmp`, report concise measurements in the completion commit, and distinguish the corrected bound path from the incorrect baseline.

## Risks / Trade-offs

- [Private driver resolver changes] → Feature-detect the callable capability and conservatively bypass when it is unavailable; retain released-version behavioral regressions.
- [Errors arise too early during classification] → Convert ordinary private-resolver failures into bypass and let the original operation validate; do not catch native read failures.
- [Session results enter global cache on misses] → Cover the shared classifier with unit cases and retain real sync/async transaction regressions.
- [Context leaks after exit or across async tasks] → Verify return to ordinary caching after bind exit and isolation between bound and unbound execution contexts.

## Migration Plan

No API or data migration is required. Applications use the existing session and cached-read APIs. Deliver this runtime correction independently of the adapter evaluation.

## Guard measurements

On Python 3.14 / PyMongo 4.18.2, median guard time over seven runs of 200,000
calls changed from 238 to 437 ns unbound, 133 to 244 ns with an explicit session,
and 237 to 354 ns bound. The baseline is `f5aa03c`; its bound result was incorrectly
cache-eligible. The corrected bound result selects session bypass. These are local
microbenchmarks, not application latency guarantees.

For 20,000 profiled unbound calls, the resolver consumed about 4 ms exclusive time
and the classifier 10 ms. Explicit-session calls did not invoke the resolver.
The resolver-failure correction was also measured against `559da66`: unbound
411 to 416 ns, explicit 239 to 237 ns, and bound 337 to 330 ns. The small shifts
are local timing variation; no new successful-path work was added. Both runs
recorded zero database commands. Command monitoring also recorded zero commands
in the original comparison. Raw output stays untracked. Reproduce the timing and profile from each checkout:

```bash
PYTHONPATH="$PWD/src" uv run --frozen --no-sync python - <<'PYTHON'
import cProfile
import pstats
import statistics
import timeit

from pymongo import MongoClient
from client_query_cache.synchronous import CacheManager


def measure(label, view, session):
    invoke = lambda: view._request_bypass_reason(session=session, kwargs={})
    timings = timeit.repeat(invoke, number=200_000, repeat=7)
    print(label, statistics.median(timings) * 1e9 / 200_000, invoke())
    profile = cProfile.Profile()
    profile.runcall(lambda: tuple(invoke() for _ in range(20_000)))
    pstats.Stats(profile).sort_stats("tottime").print_stats(6)


with MongoClient(connect=False) as client, CacheManager(client) as manager:
    view = manager["guard_profile"]["records"]
    measure("unbound", view, None)
    with client.start_session() as session:
        measure("explicit", view, session)
        with session.bind(end_session=False):
            measure("bound", view, None)
PYTHON
```
