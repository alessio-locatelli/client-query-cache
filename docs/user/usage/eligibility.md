# Observe cache eligibility

Run the [compact FastAPI self-check](../examples/fastapi-minimal.md) to see these outcomes against a disposable replica set. The fragments below come from that executable program: `owned` contains its application resources, and `observed_bypass` checks public snapshots before and after a fully consumed read.

## Miss followed by hit

With the stream healthy and the document not yet cached, the first request records one miss and the repeated request records one hit. Startup and concurrent writes can affect admission; the self-check seeds data before application startup and waits for stream readiness.

<!-- fmt:off -->

```python
--8<-- "examples/fastapi_minimal_example.py:reuse"
```

<!-- fmt:on -->

## Deliberate bypasses

Each operation below delivers a document but records one ordinary bypass and one matching reason, with no hit or miss. Returning a result alone is not evidence it was cached.

| Operation                                | `bypass_reasons` observation           |
| ---------------------------------------- | -------------------------------------- |
| Session-bound `find_one`                 | `session` increases by one             |
| `find` with `allow_partial_results=True` | `unsupported_options` increases by one |
| Aggregation with `$sample`               | `unsafe_pipeline` increases by one     |

<!-- fmt:off -->

```python
--8<-- "examples/fastapi_minimal_example.py:session"
```

```python
--8<-- "examples/fastapi_minimal_example.py:cursor"
```

```python
--8<-- "examples/fastapi_minimal_example.py:sample"
```

<!-- fmt:on -->

The sampling pipeline is executed inside the self-check's observation wrapper so the snapshot difference covers both `aggregate()` and cursor consumption. It selects the seeded book before sampling, making delivery predictable while the pipeline remains ineligible for caching.

## Oversized result

The example sets `max_entry_bytes` to 1 KiB and seeds a document with a 2,048-character description. Reading it delivers the complete document, records one miss and one `oversized_bypasses` event, and leaves ordinary `bypasses` unchanged. Repeating the read still cannot admit that document.

<!-- fmt:off -->

```python
--8<-- "examples/fastapi_minimal_example.py:oversized"
```

<!-- fmt:on -->

## Direct reads

The PATCH response uses the raw collection and leaves hit, miss, and bypass counters unchanged. A direct read is not a cache bypass: it never enters the cached view. Session-bound reads through the cached view do enter it and record `session` bypasses.

These are selected examples. The [API reference](../reference/api.md#bypass-conditions) is the complete eligibility contract, and [monitoring](../operations/monitoring.md#observability) explains counter accounting and stream health. Snapshot differences are easiest to interpret in an isolated exercise; concurrent requests contribute to the same manager-wide counters.
