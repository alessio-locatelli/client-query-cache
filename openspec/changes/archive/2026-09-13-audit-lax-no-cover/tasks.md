## 1. Audit test-harness exclusions

- [x] 1.1 Remove the unproven `tests/conftest.py` ping retry: no minimal MRE
      or repeated-run evidence supported retaining its `lax no cover` branch;
      verify the integration fixture.
- [x] 1.2 Guard Docker client construction with the fixture's runtime diagnostic
      and verify a missing socket reports it without a raw Docker traceback.
- [x] 1.3 Audit all four polling timeout guards listed in design.md, replacing
      each with a reasoned ordinary exclusion or direct failure-path test and
      verifying its stream module.
- [x] 1.4 Replace the three unreachable asynchronous test-double paths listed in
      design.md with a direct test, assertion, or deletion and verify the
      asynchronous stream tests.
- [x] 1.5 Replace the synchronous concurrent-worker `lax no cover` handlers:
      use explicit lifecycle suppression and non-lax failure reporting, then
      verify the synchronous stream tests.

## 2. Audit stream test doubles

- [x] 2.1 Remove `.coveragerc`'s `lax no cover` configuration only after a
      repository search confirms no source occurrences remain, then verify full
      coverage and strict-no-cover.

## 3. Commit evidence

- [x] 3.1 Commit every accepted file edit separately with a body that records its
      evidence and disposition; verify each commit contains only that edit.
