## 1. Consolidate coverage execution

- [x] 1.1 Remove XML output configuration and the stale e2e-omission comment while retaining the e2e omission and covdefaults as the coverage-policy source, and verify `coverage report` enforces covdefaults' branch threshold without a recipe-level threshold flag.
- [x] 1.2 Refactor `just coverage` to retain its supported runtime setup while executing bare pytest once under coverage, remove obsolete parallel-data setup and combining, preserve integrity checks, and verify `just coverage` executes unit, integration, and end-to-end tests successfully.
- [x] 1.3 Remove non-directive `justfile` comments and verify its recipes retain their current behavior.

## 2. Remove unused CI reporting

- [x] 2.1 Remove the unused coverage XML artifact generation and upload while retaining safe failure diagnostics, and verify the workflow passes `just ci-lint`.
- [x] 2.2 Remove the duplicate CI unit-test job and make the full coverage job depend only on quality, then verify the workflow passes `just ci-lint`.

## 3. Establish concise contributor guidance

- [x] 3.1 Create `CONTRIBUTING.md` as the canonical developer workflow with environment setup, the required Toolbx/Distrobox socket-enablement step before `just coverage`, and concise pointers for focused test work; verify every documented recipe and command matches the implementation.
- [x] 3.2 Update `AGENTS.md` and `docs/development.md` to direct contributors to the canonical workflow and present `just coverage` as the default full validation command without duplicating test runs; verify the three documents contain no conflicting command guidance.

## 4. Validate the streamlined workflow

- [x] 4.1 Run `just coverage`, `just lint`, and `just ci-lint`; verify the configured coverage gate, full test suite, quality checks, and workflow validation all pass.
