## Development Guidelines

### General

- Use the OpenSpec workflow for all non-trivial work.
- You must follow SOLID, DRY principles, and maintain high-quality scalable and extendable architecture.
- Performance is critical, and you must fight for every micro- and macro-optimization. For each major change, you must record profiling and benchmark measurements in the commit body.

### OpenSpec completion

- After an OpenSpec change is fully applied and has passed review, proactively run `openspec-sync-specs`, run `openspec-archive-change`, and commit every file that belongs to the completed change. Treat these as one continuous completion sequence and do not ask for confirmation between steps.
- The review may come from a subagent or an external Codex session. Any substantive edit made after that review requires another review.
- Stop the completion sequence only for a concrete blocker: incomplete artifacts or tasks, blocking review findings, failed validation, an unresolved delta-to-main-spec conflict, an existing archive target, unrelated working-tree changes that cannot be separated safely, or a commit failure that requires user judgment. Report the blocker instead of silently skipping or weakening a lifecycle step.

### Writing tests

- Use `@pytest.mark.parametrize` when the same test logic should be run against multiple input/output cases. Prefer it over duplicating nearly identical test functions.
- Setup, teardown, or cleanup logic should be placed outside the test function itself. For example, a fixture can yield an object and perform cleanup.
- Tests should not duplicate the same code (e.g., `try`/`finally` blocks or inner functions). Extract and reuse such logic instead.
- Do not write tests for impossible scenarios solely to achieve 100% code coverage. If code is unused in production, delete it immediately—do not mask it with mocking or patching in tests.

### Docstrings and code comments

- Do not write docstrings.
- Do not write code comments.
- **No historical/postmortem framing:** Phrases such as "the old default", "before this flag existed", "used to qualify for X", or "this code replaced database X" belong in postmortems, ADRs, specifications, or git commit message bodies.
- Do not repeat in prose what is already expressed by tests. Unlike prose, tests are a more reliable contract that stays in sync with the code.
- You may add a concise docstring or code comment only when the information is not already documented elsewhere **and**:
  - A business or architecture decision cannot be derived from the code (e.g., `"""We use service X instead of Y because of rate limits."""`).
  - A non-obvious hack or pitfall exists that may look like a code problem if left unexplained (e.g., `# Temporarily reduce the batch size to work around the OOM in the cloud.`).
  - There is a need to reference an external resource (e.g., `Related issue <link>.` or `See ADR-0042`).
  - There is a need to explain **why** a non-obvious action is taken (e.g., "Early exit because all items were processed", "Used a real ID in a test because…").
- Never duplicate ADRs, specifications, or any other documentation in the code. If the code requires an explanation, add a reference (e.g., `# See ADR-0042`, `# See openspec/path-to-spec/`).
- If you delete something from the file, the "why?" prose belongs in the commit body or documentation (specifications, postmortems, ADRs) — not as inline prose about functionality that no longer exists.
- If a file is already bloated with prose that violates these rules, that is not an excuse to bypass them. Instead, signal that the code needs decluttering — retain any indispensable rationale as an ADR reference instead.
- Immediately delete any pre-existing stale comments or prose that violates these rules.

_Note that ignore comments that suppress false-positives (e.g., `# noqa`, `# type: ignore`, `# pragma`) are obviously out of scope of these guidelines._

## User-facing prose (README, program output)

- **No internal implementation details.** Don't expose internal implementation-level mechanics in a README. A README is a short, high-level description for a regular user, not a spec for the internals — use a concrete illustrative example instead of a formula.
- User-facing prose (README.md, `--help` text, CLI docs) must describe _current_ behavior only, in short, high-level, user-friendly language.
- **No historical/postmortem framing.** Phrases like "the old default", "before this flag existed", "used to qualify for X" are meaningless to a reader who only has the current codebase — they imply a diff against a history the reader can't see and doesn't care about. Describe what the feature does today, full stop.
- Non-recoverable persistent failures (such as missing files, missing dependencies, permission or access errors, etc.) must not go unreported. At minimum, produce a visible error message so users can either take corrective action or report the issue.
- **Do not compete with official documentation:** Do not teach users how to install third-party tools, how to debug or configure their environment, etc. Use a short hint and a reference to the official resource.
- In the "unreleased" section, a changelog entry should describe the final behavior once, not accumulate review history.

## Commands

Run project commands through the recipes documented in [`docs/development.md`](docs/development.md).

### Setup

```bash
just setup
```

### Python package and project manager

Use [`uv`](https://docs.astral.sh/uv/).

## Development

### Lint

```bash
just lint
just format
```

If edited CI:

```bash
just ci-lint
```

### Test

```bash
just test
just test-integration
just test-e2e
just coverage
```

### Writing Commit Messages

Commit proactively during the work after completing each dedicated part of a larger task. The commit body should communicate the "why," not just the "what." Include the rationale behind the changes, non-trivial decisions, and any other information that may be useful for future developers.
