## 1. Audit test-harness exclusions

- [ ] 1.1 Audit `tests/conftest.py:89` with a minimal container-startup MRE and
      repeated-run evidence; retain `lax no cover` only for observed intermittent
      failure, otherwise make the listed non-lax replacement and verify it.
- [ ] 1.2 Audit all four polling timeout guards listed in design.md, replacing
      each with a reasoned ordinary exclusion or direct failure-path test and
      verifying its stream module.
- [ ] 1.3 Replace the three unreachable asynchronous test-double paths listed in
      design.md with a direct test, assertion, or deletion and verify the
      asynchronous stream tests.
- [ ] 1.4 Retain a synchronous concurrent-worker `lax no cover` handler only
      with an MRE and repeated intermittent evidence; otherwise use non-lax failure
      reporting and verify the synchronous stream tests.

## 2. Audit stream test doubles

- [ ] 2.1 Remove `.coveragerc`'s `lax no cover` configuration only after a
      repository search confirms no source occurrences remain, then verify full
      coverage and strict-no-cover.

## 3. Commit evidence

- [ ] 3.1 Commit every accepted file edit separately with a body that records its
      evidence and disposition; verify each commit contains only that edit.
