# Read-through collection adapter evaluation

**Recommendation: keep the explicit cached-read views. Do not adopt a transparent
read-through collection adapter under the selected live-error contract.** This
study changes no runtime behavior. The bound-session production correction was
merged independently in [#149](https://github.com/alessio-locatelli/client-query-cache/pull/149).

## The deciding requirement

The selected contract requires warm reads to preserve native server/network
errors and required server effects. A successful local hit cannot silently
replace an operation that would fail in MongoDB.

Consider two executions with the same query, warm entry and healthy invalidation
stream. In one, the native command succeeds. In the other, the server starts
rejecting that command after the entry was warmed. A read that issues no command
cannot distinguish those executions: its available information is the same.
Returning the cached value in both executions suppresses the second execution's
required error. Changing a wrapper from composition to inheritance does not add
that missing observation.

Executing the native operation preserves its errors and effects. It also removes
the avoided-database-command benefit of the tested warm paths. This is enough to
decline the proposed transparent cache under this contract; a driver-wide method
inventory and performance target do not change that boundary.

This is not a universal impossibility claim about caching. An explicit cached
API can document that a hit skips database execution, as the current views do.
A hybrid that executes natively and caches some processing might have other
benefits; this study does not evaluate or promise them. Relaxing the selected
error contract would require a new decision and compatibility investigation.

## Decisive reproduction

The directly executable [live_error.py](../../../research/collection_adapter/live_error.py)
warms `count_documents({})` using the existing cache. It then enables MongoDB's
`failCommand` fail point for that application's aggregation commands, with
non-retryable error code 2. The control client and change-stream getMore commands
are unaffected. A command listener distinguishes count aggregation from manager
change-stream creation, and library statistics establish the actual hit.

| Execution after warming | Observed outcome         | Count commands | Library hits |
| ----------------------- | ------------------------ | -------------: | -----------: |
| Native PyMongo          | OperationFailure, code 2 |              1 |            0 |
| Existing cached view    | Cached integer 1         |              0 |            1 |

The code asserts these outcomes against a disposable MongoDB 8.0.4 single-node
replica set. Both PyMongo 4.18.1 and 4.18.2 have been exercised. This example
establishes the selected error boundary, not a bug in the existing explicit-view
contract, full adapter compatibility, or certification of other deployments.

Run from the project root with the normal development dependencies and existing
container bridge:

```bash
bash -c 'set -euo pipefail
source scripts/testcontainers-bridge.sh
PYTHONPATH="$PWD/src:$PWD" uv run --frozen --no-sync python research/collection_adapter/live_error.py'
bash -c 'set -euo pipefail
source scripts/testcontainers-bridge.sh
PYTHONPATH="$PWD/src:$PWD" uv run --isolated --no-project --with pymongo==4.18.1 --with pytest==9.1.1 --with "testcontainers[mongodb]==4.15.0" python research/collection_adapter/live_error.py'
```

Each run owns its disposable container and UUID database, disables the fail point
on exit and closes its clients. No credentials file, configured database, host
setting or production service is accessed. Keep diagnostic output untracked.

## Cursor return types are a separate question

The explicit cached views return native cursor subclasses from `find()` and
`aggregate()`, including immediate asynchronous find construction. Their
[public cursor contract](../../user/reference/api.md#cached-read-methods) covers
streaming misses, complete-consumption admission, local hit snapshots, chaining,
lifecycle, and batching. This does not establish whole-collection
interchangeability: the views remain read-only, and cached hits still skip server
execution. The live-error boundary investigated above therefore remains relevant.

## Scope and limitations

The conclusion is a decision under the selected error policy. It does not reject
any native PyMongo operation, establish all-method compatibility, or certify a
cached adapter, future driver releases, third-party integrations or untested
server topologies. No benchmark threshold is needed for the decision, and this
report makes no throughput or memory guarantee.

The investigation also observed two independent issues. The existing cached
count wrapper can omit explicit `limit=0`, `limit=None` or `skip=None` options
that native reads reject; [#151](https://github.com/alessio-locatelli/client-query-cache/issues/151)
tracks that correctness issue separately from this study.
[PYTHON-6145](https://jira.mongodb.org/browse/PYTHON-6145) tracks the upstream
cursor `let` annotation mismatch. Neither issue is evidence that returning a
cursor is impossible. The production bound-session correction belongs to its
independent change, not this research outcome.
