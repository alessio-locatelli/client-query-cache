# Tasks

## 1. Aliases and tests

- [ ] 1.1 Confirm that `adopt-annotated-types` is applied: `src/client_query_cache/_types.py` exists and `AGENTS.md` contains its `cast(...)` rule. Stop if it is not. Add the design's three alias definitions to `_types.py` without comments.
- [ ] 1.2 Apply the design's classification to `tests/`. Find candidates with `rg -n 'dict\[str, (Any|object)\]' --type py tests`, and replace the two local `Document` aliases. Resolve the resulting mypy errors as the design's "Narrowing" section describes, never by reintroducing `Any`. Verify that `uv run -- mypy` and `just lint` pass, and that every remaining candidate is in the design's unchanged category.

## 2. Benchmarks

- [ ] 2.1 Apply task 1.2 to `benchmarks/`, using `rg -n 'dict\[str, (Any|object)\]' --type py benchmarks`. Keep narrowing outside timed regions. Verify that `uv run -- mypy` and `just lint` pass, and that every remaining candidate is in the design's unchanged category.

## 3. Code Quality

- [ ] 3.1 Scan the entire file for each edited or added test file, including pre-existing tests, and apply AGENTS.md's "Writing tests" guidelines, including parametrization; verify the resulting test diff.
- [ ] 3.2 If implementing with Claude Code, confirm that no new prose was added to code, and that every why explanation is in specs or commit bodies. OpenAI Codex is exempt.
