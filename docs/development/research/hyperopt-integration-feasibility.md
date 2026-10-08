# Hyperopt MongoTrials feasibility

Hyperopt 0.3.0's MongoTrials backend is unsuitable for an example in the supported Python/PyMongo environment. Its declared `mongotrials` dependency is `pymongo>=4.0.0`, but the [release source](https://github.com/hyperopt/hyperopt/blob/9834314879c09c13e0b8e93eb678408ba46441a8/hyperopt/mongoexp.py) still uses removed APIs: collection `insert`, `remove`, `update`, and `find_and_modify`, plus collection and cursor `count`. [Upstream #932](https://github.com/hyperopt/hyperopt/issues/932) tracks the compatibility defect; [PR #961](https://github.com/hyperopt/hyperopt/pull/961) proposes a port.

On CPython 3.14.6 with PyMongo 4.18.2, the published extra installs and imports. Calling `MongoTrials.new_trial_ids(1)` with a caller-owned database fails before network I/O with `TypeError`, because `job_ids.find_and_modify` is absent. That prevents a normal trial lifecycle regardless of read caching. This can be reproduced without a MongoDB server:

```sh
uv run --no-project --with 'hyperopt[mongotrials]==0.3.0' --with 'pymongo==4.18.2' -- python - <<'PY'
from types import SimpleNamespace
from hyperopt.mongoexp import MongoTrials
from pymongo import MongoClient

with MongoClient(connect=False) as client:
    trials = object.__new__(MongoTrials)
    trials.handle = SimpleNamespace(db=client["hyperopt_probe"])
    trials.new_trial_ids(1)
PY
```

`refresh_tids` repeatedly reads an experiment's IDs and versions, then fetches changed documents. Those stable polling queries could reuse cached reads between writes. Workers reserve jobs and update state, refresh timestamps, results, and attachments; each jobs-collection write invalidates query results, limiting reuse during active trials. The backend also chains native cursor `sort` and calls the removed cursor `count`; the cache's current cursor API supports the former and does not restore the latter.

No runnable Hyperopt example is included. An integration would require a compatible published backend and a separate planning decision; this repository does not repair the upstream backend.
