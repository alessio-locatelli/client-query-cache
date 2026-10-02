## Project Description

See [README.md](README.md).

## Development Guidelines

### General

- Use the OpenSpec workflow for all non-trivial work.
- **Review findings in an active change:** While a branch's OpenSpec change remains active, valid review findings belong to that change. Amend its existing delta specs, design, or tasks when needed; when existing requirements already cover the behavior, add only the necessary task, implementation, and regression test. A review round never by itself justifies a new change. Create a separate change only when the finding is outside the active change's declared scope or the user explicitly requests a split. Archive only after the whole branch has been cleanly reviewed.
- Leverage the [Generic Development Workflow](openspec/generic_development_workflow.md) when planning designs and tasks.
- You must follow SOLID, DRY principles, and maintain high-quality scalable and extendable architecture.
- Performance is critical, and you must fight for every micro- and macro-optimization. For each major change, you must record profiling and benchmark measurements in the commit body.
- Keep the usage documentation in `README.md` and `docs/` in sync with the code's public interface. Document examples, hints, gotchas, and common misuse patterns. OpenSpec files are internal specifications for development—they are not intended for end-user consumption.
- Avoid using `get()` on dictionaries. Instead, use `try`/`except KeyError` when a key may be absent.
- An `except` clause names one exception type. List several types in one clause only when the guarded code demonstrably raises each of them and a test covers each; otherwise delete the type that is never raised. Coverage marks a multi-type clause as covered as soon as one type fires, so it cannot show that the others are dead.
- Never use `contextlib.suppress`: coverage cannot show that its exception is never raised. Use `try`/`except <Type>: pass` instead, so that an unreachable handler shows up as a missed line.
- Any upstream defect (in the MongoDB server, its documentation, specification, or the official Python library) must be documented in the `docs/` with a corresponding URL pointing to a tracking ticket (if none exists on the public issue tracker, ask the user to create one).

### Generated artifacts

- Do not commit raw benchmark results, regardless of size: they can be regenerated. Store only a concise prose summary in Markdown, including the commands needed to reproduce the measurements.
- Include a JSON file only when it is genuinely important for future developers (for example, a fixed reproduction configuration), and keep it under 200 lines. Do not minify or reformat large payloads to evade this limit.
- Keep reproducible raw benchmark and diagnostic outputs untracked.

### OpenSpec completion

- After an OpenSpec change is fully applied and has passed review, proactively run `openspec-sync-specs`, run `openspec-archive-change`, and commit every file that belongs to the completed change. Treat these as one continuous completion sequence and do not ask for confirmation between steps.
- The review may come from a subagent or an external Codex session. Any substantive edit made after that review requires another review.
- Stop the completion sequence only for a concrete blocker: incomplete artifacts or tasks, blocking review findings, failed validation, an unresolved delta-to-main-spec conflict, an existing archive target, unrelated working-tree changes that cannot be separated safely, or a commit failure that requires user judgment. Report the blocker instead of silently skipping or weakening a lifecycle step.

### Writing tests

- Use `@pytest.mark.parametrize` when the same test logic should be run against multiple input/output cases. Prefer it over duplicating nearly identical test functions.
- Setup, teardown, or cleanup logic should be placed outside the test function itself. For example, a fixture can yield an object and perform cleanup.
- Tests should not duplicate the same code (e.g., `try`/`finally` blocks or inner functions). Extract and reuse such logic instead.
- Do not write tests for impossible scenarios solely to achieve 100% code coverage. If code is unused in production, delete it immediately—do not mask it with mocking or patching in tests.
- Use Hypothesis for invariants and operation-ordering over a real input space. Generate incidental values with `faker`, including realistic single-instance data. When an exact value matters, give it a descriptive name, constant, fixture, or short explanatory comment unless the file's git history already explains the choice.
- Postpone adding defensive code inside `tests/` until a real failure occurs. Fixing a failed test is cheap; maintaining prematurely added pseudo-defensive code costs context and creates false claims about an interface.
- Never write tests merely to achieve 100% coverage by masking code that never runs in a real application. Either delete dead code, or add a `# pragma: lax no cover` for cases that are flaky across runs, or add `# pragma: no cover` with a concise rationale.
- Do not write tests for helper utilities located inside the `tests/` directory. These internal test utilities do not require their own test coverage. Delete lines that are not exercised by the full test suite. Cases that genuinely depend on CI or other environment properties may use a pragma comment with a clear rationale.

### Validation, linting, formatting, testing

```bash
just lint
just format
# All tests and coverage report.
just tests_and_coverage
# Custom flags or arguments.
just pytest <any_pytest_args>
```

For more details or a first time setup see [CONTRIBUTING.md](CONTRIBUTING.md).

### Writing Commit Messages

- Commit proactively during the work after completing each dedicated part of a larger task.
- The commit body should communicate the "why," not just the "what." Include the rationale behind the changes, non-trivial decisions, and any other information that may be useful for future developers.

## User-facing prose (README, program output)

- **No internal implementation details.** Don't expose internal implementation-level mechanics in a README. A README is a short, high-level description for a regular user, not a spec for the internals — use a concrete illustrative example instead of a formula.
- User-facing prose (README.md, `--help` text, CLI docs) must describe _current_ behavior only, in short, high-level, user-friendly language.
- **No historical/postmortem framing.** Phrases like "the old default", "before this flag existed", "used to qualify for X" are meaningless to a reader who only has the current codebase — they imply a diff against a history the reader can't see and doesn't care about. Describe what the feature does today, full stop.
- Non-recoverable persistent failures (such as missing files, missing dependencies, permission or access errors, etc.) must not go unreported. At minimum, produce a visible error message so users can either take corrective action or report the issue.
- **Do not compete with official documentation:** Do not teach users how to install third-party tools, how to debug or configure their environment, etc. Use a short hint and a reference to the official resource.
- In the "unreleased" section, a changelog entry should describe the final behavior once, not accumulate review history.

## References

- [MongoDB Specifications](./specifications) repository (Git submodule).
