# Tasks

## 1. Collection-type eligibility

- [x] 1.1 Replace the shared view-only metadata representation with positive ordinary-collection eligibility and update both managers to use it. Treat absent and inconclusive metadata as uncached, retryable determinations. Verify parametrized metadata cases for ordinary, view, time-series, absent, and inconclusive results, preserving default collation and epoch refresh behavior.
- [x] 1.2 Add sync and asyncio regression coverage for all six facade read methods against real time-series collections with a healthy database stream. Verify repeated direct calls, bypass accounting, no cache admission or hits, option preservation, database-error propagation, and changed applicable results after an independent measurement insert without waiting for invalidation. Use fixtures and parametrization rather than duplicated setup or assertions.
- [x] 1.3 Cover absent-to-time-series and ordinary-to-time-series transitions, including a read between processed ordinary drop and recreation; verify no stale negative or positive result survives. Cover absent-to-ordinary recovery and retain ordinary positive/negative caching, view bypass, and retry after probe failure in both execution models.
- [x] 1.4 Update the README's current bypass guidance for time-series and absent namespaces, distinguishing an absent collection from a missing document in an existing collection. Document conservative bypass after time-series-to-ordinary recreation when no logical-namespace event refreshes metadata. Verify the text against the implemented regression behavior without expanding into the pending public-library documentation work.
- [x] 1.5 Record comparable before/after ordinary-hit measurements using the existing performance-guard workload and metadata-call counts for repeated ordinary, time-series, and absent reads. Verify ordinary hits add no metadata round trip and explain any measured regression in the implementation commit body.

## 2. Code Quality

- [x] 2.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization.
- [x] 2.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies). OpenAI Codex is exempt from this rule because it understands the difference between garbage and valuable code comments. Completed by OpenAI Codex; exemption applies.
