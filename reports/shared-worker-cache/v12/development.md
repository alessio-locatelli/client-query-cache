# Scalar and relay development diagnostics

All observations here are exploratory and excluded from the [registered study](registration.md). They retain the 1,000 requests/s cold rate and cannot select rates or establish acceptance bounds.

## Scalar cost

Five repetitions of 10,000 calls compare v11 with the scalar paths on this host. Median process CPU per call, including loop overhead, is:

| Operation                        | v11 µs | scalar candidate µs |
| -------------------------------- | -----: | ------------------: |
| Canonicalize integer             |  0.233 |               0.041 |
| Order-sensitive integer key      |  0.239 |               0.056 |
| Extract `_id` anchor             |  0.521 |               0.361 |
| Filter eligibility               |  0.460 |               0.360 |
| Normalize matching-codec integer |  0.635 |               0.102 |

Run the following with the contributor interpreter once at `970ff4b` and once at this registration's candidate. These isolated costs are not request latency estimates.

```python
import statistics
import time

from bson.codec_options import CodecOptions
from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.identity_reads import (
    extract_id_anchor,
    normalize_identity_for_cache_key,
)
from client_query_cache._core.order_sensitive_keys import order_sensitive_key
from client_query_cache._core.read_validation import is_filter_cacheable

values = tuple(range(10_000))
queries = tuple({"_id": value} for value in values)
options = CodecOptions()
operations = (
    ("canonicalize", canonicalize, values),
    ("ordered identity", order_sensitive_key, values),
    ("id anchor", extract_id_anchor, queries),
    ("filter eligibility", is_filter_cacheable, queries),
    (
        "normalize integer",
        lambda value: normalize_identity_for_cache_key(value, options, options),
        values,
    ),
)
for label, operation, inputs in operations:
    samples = []
    for repeat in range(5):
        start = time.process_time()
        for value in inputs:
            operation(value)
        samples.append((time.process_time() - start) * 100)
    print(label, statistics.median(samples), "µs/call")
```

## Relay diagnosis

Six balanced async/four-worker cold blocks with scalar paths and the original relay retain a 2.535 ms P99 delta. Disabling owner GC, releasing the native enqueue GIL and yielding owner execution do not reliably remove large deltas in separate diagnostics. Those prototypes are discarded. A direct-connection diagnostic bypasses the relay and its byte oracle: all twelve deltas are below 0.87 ms. It is an isolation experiment and cannot support acceptance.

A subsequent twelve-block diagnostic keeps the byte oracle and enables `TCP_NODELAY` on both relay sockets. All thirty-six windows complete healthily. Per-block shared-minus-direct P99 deltas in milliseconds are 0.314, 1.047, 0.746, 0.628, 0.831, 0.675, 1.147, 0.439, 0.897, 0.569, 0.932 and 0.815. This suggests the relay policy contributes to the observed tail; it does not prove a causal speedup or a stable registered bound. PyMongo 4.18.2's synchronous and asynchronous connection setup both enable `TCP_NODELAY` in `pymongo/pool_shared.py`.

Reproduce the relay diagnostic by copying v11's config under `/tmp/agents/`, keeping twelve cold blocks, and running the registered candidate with `--phase cold --only async:4`. Run v11 plus the scalar patch for the original-relay control. The `--only` run is exploratory; complete qualification and all required cells remain mandatory. Raw diagnostic reports remain under `/tmp/agents/issue-272-continuation/`.
