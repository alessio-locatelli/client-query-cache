# Pull-request performance guard

Every pull request runs a required **Cache hot-path performance guard** check. It compares the base and proposed revisions on the same runner for a small set of representative operations: cached `find_one` hits (synchronous and asynchronous), bounded `find` admission, and change-event invalidation, each at two document sizes. The check skips its timed comparison, and passes immediately, when a pull request changes no Python code, dependency lockfile, or guard input.

The guard measures repeated, alternating blocks of both revisions and only fails a case when the proposed revision is stably 30% or more slower than the base revision. Ordinary run-to-run noise is reported as an inconclusive warning instead of a failure, so occasional runner variance does not block unrelated work. A missing baseline, an incompatible workload, or another setup problem is reported as a distinct measurement failure rather than a silent pass.

The check's step log and job summary list, per case, the base and head timings, the relative change, the decision, and both compared revisions. The full result, containing no application documents or credentials, is attached as a downloadable artifact. Rejected completed measurements remain in the artifact, and the failure reason identifies the offending block.

This guard covers four representative hot paths on one runner; it does not replace the stream-cost benchmark's controlled matrix or decision evidence in the [public measurement guide](../user/benchmarks/stream-cost.md). Use the manual workflow to investigate a broader cost question or a specific workload.

When a pull request intentionally trades performance for another benefit, the guard still reports the measured slowdown. A maintainer records the accepted cost and its justification during review, then applies the repository's maintainer-only merge exception for that pull request; pull-request authors cannot suppress or bypass the check themselves.
