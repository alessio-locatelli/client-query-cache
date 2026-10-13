# Timed shared-cache fault results: version 6

The run at `a1b188e23255ac8a6ee1269681bea16fb2a4d0cc` does not establish the registered safety claims. [PR #276](https://github.com/alessio-locatelli/client-query-cache/pull/276) identified first-key-only detection and duplicate scenarios with idle workers in the during-local-hit cases. Its timings are withdrawn as complete fault evidence.

The [registration](registration.md) describes the corrected scenario procedures and reproduction commands. The frozen configuration is unchanged. Version 5's failed miss-latency and capacity criteria remain independent of this fault phase.
