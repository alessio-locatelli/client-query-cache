# Tasks

List candidates with `rg -n --type py '\b(int|float)\b' <tree> | rg -v 'isinstance\(|\b(int|float)\('` and classify each with the design's rules.

## 1. Library

- [x] 1.1 Apply the integer rule in `src/`, keeping each synchronous/asynchronous pair identical. Verify that `just lint` passes.
- [x] 1.2 Add `NonNegativeFloat` to the alias module and apply the floating-point rule in `src/`, keeping each synchronous/asynchronous pair identical. Verify that `just lint` passes.
- [x] 1.3 Extend the constrained-annotations bullet in `AGENTS.md` with both rules. Verify that `just lint` passes.

## 2. Benchmarks and tests

- [x] 2.1 Apply the integer rule in `benchmarks/`. Verify that `uv run -- mypy` and `just lint` pass.
- [x] 2.2 Apply the floating-point rule in `benchmarks/`. Verify that `uv run -- mypy` and `just lint` pass.
- [x] 2.3 Apply both rules in `tests/`. Verify that `just tests_and_coverage` passes.

## 3. Code Quality

- [x] 3.1 If implementing with Claude Code, confirm that no new prose was added to code, and that every why explanation is in specs or commit bodies. OpenAI Codex is exempt.
