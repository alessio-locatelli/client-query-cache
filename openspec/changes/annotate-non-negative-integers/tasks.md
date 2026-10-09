# Tasks

List candidates with `rg -n --type py '\bint\b' <tree> | rg -v 'isinstance\(|\bint\(|map\(int'` and classify each with the design's rules.

## 1. Library

- [x] 1.1 Apply the rule in `src/`, keeping each synchronous/asynchronous pair identical. Verify that `just lint` passes.
- [x] 1.2 Extend the constrained-annotations bullet in `AGENTS.md` with the rule. Verify that `just lint` passes.

## 2. Benchmarks and tests

- [ ] 2.1 Apply the rule in `benchmarks/`. Verify that `uv run -- mypy` and `just lint` pass.
- [ ] 2.2 Apply the rule in `tests/`. Verify that `just tests_and_coverage` passes.

## 3. Code Quality

- [ ] 3.1 If implementing with Claude Code, confirm that no new prose was added to code, and that every why explanation is in specs or commit bodies. OpenAI Codex is exempt.
