# Tasks

## 1. Effective session bypass

- [x] 1.1 Measure and profile the existing collection request guard under unbound, bound, and explicit-session contexts using a disconnected client and an untracked `/tmp` script; record the command and concise baseline before editing the guard.
- [x] 1.2 Resolve effective bound-session context in the shared request classifier, wire both cached collections, and preserve native InvalidOperation error ordering. Cover the shared decision boundary with a small unit matrix and real sync/async regressions for warm transactions, cold admission, omitted/None sessions, foreign-context validation, explicit precedence, bind exit and async task isolation.
- [x] 1.3 Clarify session bypass in user consistency guidance and the changelog; document the resolver dependency in development architecture guidance. Rerun the guard measurements and record the measured cost and unchanged network operation count in the completion commit, without committing raw diagnostics.

## 2. Code Quality

- [x] 2.1 Scan the entire file for edited or added tests and ensure that the Writing Tests guidelines from `AGENTS.md` are applied, including test parametrization.
- [x] 2.2 Confirm that no new prose was added to code if executing as Claude Code. Not applicable: this change is applied by OpenAI Codex.

## Review corrections

- [x] Add a conservative compatibility fallback for an absent/non-callable private resolver and a small shared-classifier unit matrix.
- [x] Replace mirrored integration Cartesian products with shared sync/async transaction, error-precedence, bind-exit and async task-isolation regressions.
- [x] Validate both supported released drivers, full coverage, guard measurements and independent fix scope before rearchiving.

## Resolver-failure review corrections

- [x] Treat ordinary private-resolver failures as session bypass, preserving explicit-session precedence and native error handling; cover changed signature and implementation failures.
- [x] Add one shared sync/async warm estimated-count regression in a bound transaction and compare native errors and cache activity.
- [x] Validate both released drivers, full coverage and guard cost; review, sync, archive and fold these corrections into the independent PR commit.
