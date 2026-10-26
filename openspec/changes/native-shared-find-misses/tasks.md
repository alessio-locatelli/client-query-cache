# Tasks

## 1. Native key preparation

- [x] 1.1 Implement the native paired-key encoder and binding; compare its exact bytes and errors against the existing wire encoder over generated canonical families, all supported scalar profiles, signed/Int64 limits and large keys. Restore the main generic index implementation and remove rejected family state, local-find admission and obsolete floor code.
- [x] 1.2 Integrate bounded paired-key reuse in the worker key cache; verify hits, eviction, per-key retained-size boundaries and unretained large pairs in `tests/shared_cache/test_wire.py`. Preserve the existing generic encoding path.

## 2. Shared cursor integration

- [x] 2.1 Reuse the pair across local lookup and existing owner selection in sync/async cursors; verify single traversal, exact/covering/unlimited/negative/Int64 selection, no-local-index mode, unportable keys and interrupted cursors. Update `docs/development/shared-cache.md` for the resulting maintenance contract and check public guides and Context7 for affected meaning.

## 3. Current-release evidence

- [ ] 3.1 Execute the finite Rust correction comparison registered in `reports/shared-worker-cache/current-costs/plan.md`, including separate attribution. Record source/binary identities, resource and cache outcomes, all negative results and reproducible commands; resolve every reproducible regression before acceptance.
- [ ] 3.2 Compare the registered unchanged existing-test selection against main in three alternating pairs, separately from new cases, and retain warning-free timing evidence.

## 4. Code Quality

- [x] 4.1 Scan entire edited test files against the AGENTS Writing Tests guidelines, including parametrization.
- [x] 4.2 The Claude-only prose restriction is inapplicable: this change is prepared by OpenAI Codex.
