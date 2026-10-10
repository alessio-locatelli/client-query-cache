# Tasks

## 1. Aliases and tests

- [x] 1.1 Confirm that `adopt-annotated-types` is applied: `src/client_query_cache/_types.py` exists and `AGENTS.md` contains its `cast(...)` rule. Stop if it is not. Add the design's three alias definitions to `_types.py` without comments.
- [x] 1.2 Apply the design's classification to `tests/`. Find candidates with `rg -n 'dict\[str, (Any|object)\]' --type py tests`, and replace the two local `Document` aliases. Resolve the resulting mypy errors as the design's "Narrowing" section describes, never by reintroducing `Any`. Verify that `uv run -- mypy` and `just lint` pass, and that every remaining candidate is in the design's unchanged category.

## 2. Benchmarks

- [x] 2.1 Apply task 1.2 to `benchmarks/`, using `rg -n 'dict\[str, (Any|object)\]' --type py benchmarks`. Keep narrowing outside timed regions. Verify that `uv run -- mypy` and `just lint` pass, and that every remaining candidate is in the design's unchanged category.

## 3. Code Quality

- [x] 3.1 Apply AGENTS.md's "Writing tests" guidelines to the test code this change edits, and verify the resulting test diff. At the user's request, the full-file pass over pre-existing tests, including parametrization, ships separately on the `parametrize-duplicated-tests` branch.
- [x] 3.2 If implementing with Claude Code, confirm that no new prose was added to code, and that every why explanation is in specs or commit bodies. OpenAI Codex is exempt.
