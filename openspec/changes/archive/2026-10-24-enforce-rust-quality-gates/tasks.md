# Tasks

## 1. Native static enforcement

- [x] 1.1 Add pinned project-local setup, Rust formatting and Clippy recipes, dependency policies, and hooks following design.md; verify actual tools accept the current graph and reject an unused function and formatting defect in a disposable copy. Document prerequisites and update ownership with these changes.

## 2. CI integration

- [x] 2.1 Add single native static and dependent unit/model jobs, select every relevant input, and remove duplicate Cargo execution from the Python matrix. Extend existing scope tests for the new inputs and document required checks; verify the scope tests and inspect the workflow dependency graph.

## 3. Code Quality

- [x] 3.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure the Writing Tests guidelines from AGENTS.md are applied, including test parametrization.
- [x] 3.2 Confirm no new prose was added to code if using Claude Code. Inapplicable: implemented by OpenAI Codex.
