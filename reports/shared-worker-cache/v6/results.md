# Timed shared-cache fault results: version 6

The run at `ab53e506e1056c7d3b36d776b3ff01492734fa57` is withdrawn as complete recovery safety evidence. The [PR #276 re-review](https://github.com/alessio-locatelli/client-query-cache/pull/276) identified premature cached hits that the readiness gate could conceal. First-hit evidence must be retained independently and validated against worker eligibility and bracketing owner observations.

The [registration](registration.md) describes the corrected procedures and reproduction commands. Its frozen configuration is unchanged. Version 5's failed miss-latency and capacity criteria remain independent of this fault phase.
