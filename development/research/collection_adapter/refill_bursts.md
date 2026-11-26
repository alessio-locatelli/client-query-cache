# Exact-`_id` cache refill benchmark

Run from the repository root with its development environment and a local container runtime.

```bash
source development/scripts/testcontainers-bridge.sh
env -u VIRTUAL_ENV uv run -- python -m development.research.collection_adapter.refill_bursts --rounds 8 --pool 12
```

Each burst starts with eight callers. The runner warms the keys, updates the documents, and waits for the cache to process the writes before each miss burst. It uses a disposable MongoDB replica set and primary, majority reads. A server failpoint delays all application finds by 5 or 80 ms, or delays only the first find by 80 ms. Ordinary timing, warm hits, direct reads, and distinct keys provide controls.

The runner schedules callers outside the library and measures each caller from the start of the burst. Waiting callers perform their own cache lookup after the first completed refill or the wait limit. The backup policy starts one additional read after 10 ms and counts it through completion. The 2 s cap on waiting for the leader keeps the experiment bounded. These are successful-refill scenarios. The output includes finds, latency, process CPU, and peak application finds in flight.

## Findings

Two runs each on MongoDB 9.0.4, PyMongo 4.19.0, and CPython 3.15.1 with pool size 12. The server failpoint's counter verifies how many finds received the delay. The table reports the range of finds per burst and the range of median caller latencies across both runs and client models.

| Policy                       | All finds delayed by 80 ms | First find delayed by 80 ms |
| ---------------------------- | -------------------------- | --------------------------- |
| Independent reads            | 8 finds / 81.6–82.2 ms     | 4–8 finds / 2.3–2.9 ms      |
| Wait up to 50 ms             | 8 finds / 132.3–132.7 ms   | 8 finds / 52.9–53.3 ms      |
| Wait for the first read      | 1 find / 80.8–81.7 ms      | 1 find / 81.0–81.6 ms       |
| Start one backup after 10 ms | 2 finds / 80.9–81.7 ms     | 2 finds / 11.6–11.8 ms      |

At ordinary timing and with the 5 ms delay, all three coordination policies cut eight same-key finds to one. The warm control used zero finds and distinct keys used eight.

When all finds were delayed by 80 ms, the 50 ms wait raised caller p95 from 82–83 ms to 133–134 ms and median process CPU per burst from 3.0–4.4 ms to 4.0–5.0 ms. Peak in-flight finds, a proxy for connection-pool pressure, stayed at eight. Waiting for the first read kept p95 near 82 ms and cut the peak to one and CPU to 1.1–2.0 ms. Starting a backup brought the peak to two and p95 to about 91 ms. With only the first find delayed, p95 was about 81–82 ms across policies.

Keep independent reads and the existing API. A short fixed wait can add latency while preserving the full burst of MongoDB reads. A longer wait can save reads during a systemic slowdown and make every caller inherit an isolated slow read. One backup limits that delay while adding a second find and delaying callers who could otherwise finish quickly.

A public wait setting would require users to diagnose overlapping misses and tune for the same trade-offs. Reconsider coordination when representative production traces show repeated same-key misses after invalidation and a material effect on MongoDB load, connection checkout, or caller latency. The trace needs to distinguish systemic slowness from isolated slow reads.
