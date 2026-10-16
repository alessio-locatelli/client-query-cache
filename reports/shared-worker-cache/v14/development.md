# Default identity classification cost

An isolated comparison executes the actual synchronous shared `find_one` wrappers at v13 (`80aa427`) and this candidate, substituting the same successful identity-selection callback for both. A `MongoClient(connect=False)` supplies real default codec/read settings and bound-session inspection; a minimal manager returns eligible metadata without I/O. Thus this measures classification, not MongoDB latency or native hit lookup.

Five alternating 10,000-call batches with `{"_id": 7}`, after 100 warmup calls per batch, give median thread CPU costs of **2.060 µs at v13 and 1.098 µs with single-pass classification**. This does not establish request-tail improvements. The complete registered study remains necessary.

Reproduce by loading v13's `src/client_query_cache/_shared/adapters.py` into a separate module alongside this candidate. Construct each `SharedCachedCollection` with the same raw collection, eligible manager and default namespace. Replace each class's `_find_one_by_id` with the same callback returning `{"_id": 7}`. Time five alternating batches using `time.thread_time_ns()`, retaining identical loop/warmup overhead. The scratch harness is `/tmp/agents/issue-272-continuation/v14-classification-cost.py`; no diagnostic samples contribute to acceptance.
