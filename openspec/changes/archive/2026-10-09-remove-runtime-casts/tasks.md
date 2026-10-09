# Tasks

## 1. Library boundaries

- [x] 1.1 Replace all casts in `src/client_query_cache` using the design's static-boundary approach; confirm no cast calls remain and existing sync/async collection, cursor, codec, and projection tests retain their behavior.

## 2. Application and measurement boundaries

- [x] 2.1 Remove recurring casts in examples and benchmark callbacks; retain only permitted setup/reporting casts, checking example type checking and existing example and instrumentation tests.

## 3. Code Quality

- [x] 3.1 Review edited test files against AGENTS.md, including parametrization (no test files changed).
- [x] 3.2 Check Claude-specific prose restriction (OpenAI Codex exempt).
