# py-abac integration

The adapter routes py-abac's policy lookups through cached `find_one`, `find`, and `aggregate`, while policy creation and updates remain on the raw MongoDB storage. It converts materialized query results into policy iterators expected by py-abac.

The program checks hits for all three retrieval shapes, authorizes a request, updates the policy from allow to deny, and polls until invalidation changes the authorization result. This demonstrates eventual invalidation. Applications that must re-authorize against current policy on every request should use direct reads; see [consistency](../usage/consistency.md#freshness-and-authorization) and [security](../operations/deployment.md#security).

See the [example catalogue](index.md) for prerequisites, run commands, expected evidence, and the database-reset warning.

## Complete program

The code below is included from the [canonical Python source](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/py_abac_example.py).

<!-- fmt:off -->

```python
--8<-- "examples/py_abac_example.py"
```

<!-- fmt:on -->
