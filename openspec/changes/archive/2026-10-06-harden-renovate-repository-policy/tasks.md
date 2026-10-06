# Tasks

## 1. Repository changes

- [x] 1.1 Update `renovate.json5` according to design Preset composition and the delta spec's budgets/window. Preserve extraction, ownership exclusions, coupled groups, and age handling; remove MongoDB/Python/Node version-cap rules and redundant defaults. Run `prek run renovate-config-validator --files renovate.json5` and official extraction/lookup dry runs (`renovate --platform=local --dry-run=extract` / `--dry-run=lookup`). Inspect resolved policy for excluded subpresets, disabled Renovate-owned automerge, major eligibility, and digest exceptions; confirm MongoDB extraction includes both `tests/conftest.py` and `benchmarks/stream_cost/topology.py` in the coupled group. Keep diagnostics untracked; report lookup/authentication failures as incomplete evidence.
- [x] 1.2 Apply the delta spec's per-ecosystem version-PR cap in `.github/dependabot.yml`, retaining existing schedules, cooldowns, and ownership.
- [x] 1.3 Add `.github/workflows/dependency-automerge.yml` using design Shared App acceptance for both bots, including the main-only operator dispatch with `pr_number` for existing PRs. Validate with the existing actionlint and zizmor hooks. Inspect the default-branch validation-completion handoff and dispatch authorization, trusted execution boundary, bot/repository/head checks, commit-specific approval, token scope, inactive-configuration notice, and native auto-merge command; use no custom CI poller or unconditional merge. Exercise metadata selection and acceptance with representative API responses for both bots, stale heads, ineligible PRs, missing configuration, and API failures; retain live secret availability as operator acceptance evidence.

- [x] 1.4 Make `.node-version` Renovate-owned through its native nodenv manager. Consume it from CI and the container, update tooling cache keys and CI scope, and replace fixed Node-track contracts with shared selection. Verify official extraction/lookup, Node-only scope regression, and the real container build/tool check.

- [x] 1.5 Preserve Python 3.14 coverage while Renovate advances default development to newer stable releases. Derive packaging/full-test matrices from the package minimum and `.python-version`, aggregate all lanes behind a stable required check, honor each lane in isolated package validation, and resolve the container interpreter dynamically. Document independent compatibility-baseline hooks. Validate matrix generation, uv overrides, stable gate failures, official workflow hooks, and the real container smoke check.

- [x] 1.6 Retain the exact declared minimum Python patch in every compatibility matrix. Deduplicate only identical requests. Verify current-minimum, later-patch, next-release, and intermediate-release selections with parametrized regression tests against `scripts/ci_python_matrix.py`, which the workflow calls; align the contract and contributor guidance.

## 2. Contributor guidance and operator handoff

- [x] 2.1 Update `docs/development/executable-version-updates.md` to match the implemented configs and retain the executable inventory and official dry-run commands. Document policy limits and their security/manual-rebase exceptions, major-update parity, unpinned DNF exclusions, and the tag-only MongoDB override with its upstream issue link. Add the post-merge activation and rollback checklist from design Deployment boundary, including read-only verification commands (`gh api repos/alessio-locatelli/client-query-cache/rules/branches/main` and repository metadata), exact App credential names, required check identities resolved from existing CI, and evidence cases. State that settings/App/secret writes are operator work after the code lands, not coding-agent tasks; distinguish a reviewed code PR from activated automation. Include hosted config-discovery diagnosis without claiming local validation proves hosted success.

## 3. Code Quality

- [x] 3.1 Review edited or added test files against AGENTS.md Writing Tests rules. Check the parametrized CI scope regression and use official tooling plus the existing container smoke check for the shared Node selection.
- [x] 3.2 If applying with Claude Code, confirm no new prose in code. Inapplicable: OpenAI Codex is exempt.
