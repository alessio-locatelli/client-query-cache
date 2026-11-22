## Context

See `proposal.md` (Why). Constraints found in the current tree that shape the approach:

- `benchmarks/` and `scripts/` are regular Python packages (empty `__init__.py`); `research/` is an implicit namespace package. Tests, harnesses, CI, the `justfile`, and guides import or run them by module path (`from benchmarks.stream_cost...`, `python -m scripts.ci_scope`, `mock.patch("benchmarks....")`). The maintained benchmark `benchmarks/public_shared_cache.py` and five test modules import `research.*`. Several modules derive the repository root from `Path(__file__).parents[N]`, and some read fixtures through repository-relative literals such as `Path("reports/stream-cost/await-v1/config.v1.json")`.
- The performance-regression guard (`benchmarks/stream_cost/guard_runner.py`) checks out the base revision in a worktree, copies the head's workload files into `<worktree>/benchmarks/stream_cost/`, and runs `python -m benchmarks.stream_cost.guard_workload` there. The base of the pull request that performs this move still has the old layout.
- `scripts/build_versioned_docs.py` builds the stable edition from the latest release tag and extracts `docs/user`, `examples/README.md`, `examples/*.py`, and `zensical.toml` from it. Every existing release tag keeps examples at the root, and the `public-library-documentation` spec allows assembly from any locally available release tag.
- maturin builds the extension from `native/shared-index/Cargo.toml` with `python-source = "src"`. Cargo's default target directory sits next to the manifest; locally it holds about 2 GB in about 8,000 files and is ignored by `.gitignore`'s `target/` pattern. mypy (`files = src, ...`) and vulture (`paths = ["src", ...]`) walk `src/` without consulting `.gitignore`; ruff, typos, ast-grep, and the pre-commit file list honor it.
- ast-grep discovers `sgconfig.yml` by searching the working directory and its ancestors; the pre-commit hooks invoke `ast-grep scan` and `ast-grep test` without `--config`.
- `context7.json` indexes only `docs/user`; zensical publishes only `docs/user`. Snippets resolve relative to the repository root.

## Goals / Non-Goals

**Goals:**

- The tracked root matches the `development-environment` requirement "Top-level directories are conventional or tool-required".
- Every moved tool keeps working from the repository root with no `PYTHONPATH`, `pythonpath`, or `mypy_path` configuration.
- The wheel keeps its file list and Python sources; its extension builds from unchanged Rust sources.

**Non-Goals:**

- Root-level files (configuration, lockfiles, licence, guides) stay where they are; many tools read them only from the root.
- Untracked, ignored output directories that tools or recipes create on demand (`site/`, `dist/`, `.venv/`, `memory-reports/`, `benchmark-reports/`, `guard-reports/`, logs) are not part of the tracked layout.
- Archived OpenSpec changes and released `CHANGELOG.md` entries are historical records and keep the paths that were true when they were written. No changelog entry is added: the package is unchanged.
- Restructuring content inside the moved directories, such as merging `docs/examples/README.md` with `docs/user/examples/index.md` or turning research harnesses into regular packages.

## Decisions

### D1. Target layout

| Current path                               | New path                           |
| ------------------------------------------ | ---------------------------------- |
| `benchmarks/`                              | `development/benchmarks/`          |
| `research/`                                | `development/research/`            |
| `scripts/`                                 | `development/scripts/`             |
| `rules/`                                   | `development/ast-grep/rules/`      |
| `rule-tests/` (including `__snapshots__/`) | `development/ast-grep/rule-tests/` |
| `examples/`                                | `docs/examples/`                   |
| `reports/`                                 | `docs/development/reports/`        |
| `specifications/` (Git submodule)          | `docs/specifications/`             |
| `native/shared-index/`                     | `src/shared-index/`                |

`.agents/`, `.claude/`, `.github/`, `openspec/`, `docs/`, `src/`, and `tests/` stay. `sgconfig.yml` stays at the root (see D4). The submodule keeps its registered name `specifications`; only its path changes.

Alternatives, per group (the user chose the first three):

- Contributor tooling in `development/` versus `tools/` versus nesting benchmarks and rules under a root `scripts/`. `development/` mirrors the existing `docs/development/` audience split and gives one home to all contributor tooling. `tools/` is an equally common name but less specific. Nesting under `scripts/` avoids a new directory but files a 60-module benchmark package and lint rules as "scripts". Conclusion: `development/`; nothing further needed.
- Research harnesses in `development/research/` versus `docs/development/research/` beside the research notes. The harnesses are executable, linted, and tested code imported by a maintained benchmark; under `docs/` they would make `docs` an import root and put Python modules among prose. Conclusion: `development/research/`; the notes and results stay in `docs/development/`.
- Examples in `docs/examples/` versus `docs/user/examples/` versus the root. Under `docs/user/` zensical would publish the raw programs and README as static files; the root fails the layout requirement. Conclusion: `docs/examples/`.
- Reports in `docs/development/reports/` versus `docs/reports/`. Reports are maintainer evidence for the guides in `docs/development/`, which already link to them, and `docs/` stays split by audience. Conclusion: `docs/development/reports/`; nothing further needed.
- Submodule in `docs/specifications/` versus `docs/development/specifications/` versus the root. It is upstream reference material rather than this project's development guidance, and agents find it from the `AGENTS.md` reference link regardless of depth. Conclusion: `docs/specifications/`; nothing further needed.

### D2. Python module paths follow the filesystem

Add an empty `development/__init__.py`, so `development` is a regular package, and rewrite every module reference to the new dotted path: `benchmarks.` → `development.benchmarks.`, `scripts.` → `development.scripts.`, `research.` → `development.research.`. This covers imports, `python -m` commands, `mock.patch`/`monkeypatch` targets, `runpy` and subprocess module names, and module strings in guides. `development/research/` stays an implicit namespace package, as `research/` is today.

Alternatives:

- Keep the top-level names `benchmarks`, `scripts`, `research` and put `development/` on the import path. Pros: no import rewrite. Cons: pytest `pythonpath`, mypy `mypy_path`, every `python -m` in the `justfile`, CI, and guides, and every subprocess a test or harness launches would need the extra path; a command copied from a guide fails without it. Rejected.
- `development/` as a namespace package without `__init__.py`. Pros: one file fewer. Cons: mypy derives module names from the nearest directory without `__init__.py`, so `files = development/benchmarks` would yield `benchmarks.*` while the code imports `development.benchmarks.*`, which needs `explicit_package_bases` and `mypy_path`. Rejected.

Unknowns: none; the full test suite and mypy exercise every rewritten import.

### D3. The native crate moves to `src/shared-index/`; Python tools target the package directory

`src/shared-index/` keeps the crate self-contained beside the Python package it builds. maturin's `manifest-path`, the uv cache keys, Dependabot's Cargo directory, the `justfile` Cargo commands, `scripts/native-coverage.sh`'s `CARGO_TARGET_DIR`, the `rust-lint` hook filter, CI's Cargo step, the dependency-automerge path list, `ci_scope.py`, and `guard_scope.py` follow it. Because Cargo's target directory now sits under `src/`, the tools that walk `src/` regardless of `.gitignore` point at `src/client_query_cache` instead: mypy `files` and vulture `paths`.

Alternatives:

- Keep `native/` at the root. Pros: no change to build paths; the 2 GB target tree stays out of `src/`. Cons: violates the layout requirement although nothing prevents the move. Rejected.
- `src/native/shared-index/`. Pros: groups possible future crates. Cons: an extra level for the only crate, and the editable install puts `src/` on `sys.path`, which makes `native` importable as an empty namespace package (`shared-index` is not an identifier). Rejected.
- Keep `files = src` and add `target` exclusions to mypy and vulture. Pros: future top-level modules under `src/` are picked up automatically. Cons: two exclusion patterns that must track Cargo's layout; `src/` is meant to hold the one distribution package. Rejected.

Unknowns: whether maturin's sdist or wheel picks up anything new now that the crate sits inside `python-source`, and whether a wheel still builds from that sdist. Resolved by `tasks.md` task 4.2.

### D4. ast-grep rules move under `development/ast-grep/`; `sgconfig.yml` stays at the root

`sgconfig.yml`'s `ruleDirs` and `testConfigs.testDir` point to `development/ast-grep/rules` and `development/ast-grep/rule-tests`; snapshots keep ast-grep's default `__snapshots__` directory inside the test directory. Directory names keep ast-grep's scaffold defaults (`rules`, `rule-tests`) so that `ast-grep new` output matches.

Alternatives:

- Move `sgconfig.yml` as well. Cons: every CLI, hook, and editor invocation would need `--config`, because ast-grep discovers the file from the working directory upward. Rejected.
- `tests/ast-grep/`. Pros: rule tests are tests. Cons: the rules are lint configuration, not tests, and `tests/` is pytest's tree. Rejected.

### D5. The regression guard places the head workload at the head's own module path

`guard_runner.py` derives the workload package path and module name from its own `__package__` (for example `development.benchmarks.stream_cost` and `development/benchmarks/stream_cost`) instead of hard-coding `benchmarks/stream_cost`. When it copies the head's workload files into the base worktree, it creates that package directory and copies each `__init__.py` from the repository root down to the workload package, so the copied workload imports only itself and the base revision's installed library. The digest and the `python -m` target use the same derived path. This keeps the guard requirement "Guard decisions compare matched base and proposed runs" satisfied on the pull request that performs this move, whose base still keeps the harness in `benchmarks/`.

The directory creation and `__init__.py` copying are temporary transition code, needed only while a guard base predates the move. Removal condition: the move is on `main`. The second pull request deletes them and their regression case (`tasks.md` group 8); the `__package__` derivation stays because it only replaces a hard-coded path. Track removal in [GitHub issue #487](https://github.com/alessio-locatelli/client-query-cache/issues/487).

Alternatives:

- Leave the runner unchanged. Cons: the move's own pull request fails to copy the workload, so its guard cannot measure. Rejected.
- Keep the transition code permanently so that any pre-move base stays measurable. Cons: the project bans permanent compatibility fallbacks, and after the move every pull request's base already has the new layout. Rejected.
- Detect the base layout and copy into its location. Cons: the copied head files import `development.benchmarks...` and would need source rewriting. Rejected.

Unknowns: none; a regression test builds a base revision without the head's package path.

### D6. Documentation assembly temporarily reads examples from either location

`extract_corpus` lists `docs/user`, `docs/examples`, `examples`, and `zensical.toml` from the selected revision and keeps the example programs and catalogue README found under whichever example directory that revision has; `edition_config` rewrites links in that README. Without this, the stable edition, built from the latest release tag that still keeps root `examples/`, fails the strict build as soon as the move reaches `main`.

The root `examples` location is temporary transition code. Removal condition: the latest published GitHub Release keeps its examples in `docs/examples/`. The second pull request deletes the root location and its test parametrization (`tasks.md` group 8), after which pre-move release tags can no longer be assembled; see the `public-library-documentation` requirement "Combined builds discover the published release". Track removal in [GitHub issue #487](https://github.com/alessio-locatelli/client-query-cache/issues/487).

Alternatives:

- Only `docs/examples` from the start. Cons: documentation publication and every pull request's documentation build fail from the merge until the next release. Rejected.
- Keep both locations permanently so that every historical tag stays buildable. Cons: the project bans permanent compatibility fallbacks. Rejected.
- Extract the files named by each page's snippet directives. Pros: independent of any directory name. Cons: requires parsing snippet syntax (including section suffixes such as `:imports`) and re-validating paths that the current fixed allowlist confines to the corpus. Disproportionate for a transition that ends with the next release. Rejected.

### D7. Reference updates

Move with `git mv` (the submodule included, which updates `.gitmodules`) so that history follows the files. Rewrite references mechanically, then review the diff:

- Dotted module paths: a substitution of `(?<![\w.])(benchmarks|research|scripts)\.(?=[a-z_])` in tracked `*.py`, `*.md`, `*.yml`, `*.toml`, and `justfile`; English words such as "scripts." at a sentence end are followed by a space or newline and do not match.
- Bare package imports (`from benchmarks import public_shared_cache`, `from scripts import pgo_training`): a substitution of `^(\s*)(from|import) (benchmarks|research|scripts)\b(?!\.)` with `\1\2 development.\3` in tracked `*.py`.
- Slash paths: a substitution of `(?<![\w./-])(benchmarks|research|scripts|examples|reports|rules|rule-tests|specifications|native/shared-index)/` with the D1 targets in all tracked text files. Relative links (`../research/x.md`) are preceded by `/` and are not touched; links inside and into moved Markdown files are recomputed by hand.
- Bare directory names in tool configuration (`"specifications"`, `files = src, tests, benchmarks`, `--ignore=specifications`, `^specifications`, `^examples`) are edited one by one.
- `Path(__file__).parents[N]` depths increase by one for every module that moved one level deeper.
- GitHub URLs that point to `blob/main` or `tree/main` are updated; URLs pinned to a commit SHA or tag keep the old path, which still resolves at that revision.
- Historical evidence: commands, module paths, and file paths in `docs/development/reports/` and `docs/development/research/` that record how a measurement was taken at a stated or pinned revision keep their original form, because they must run against that revision's checkout. The mechanical substitutions skip these two trees; each hit there is reviewed by hand, which updates only relative links, `blob/main`/`tree/main` URLs, and commands the document presents for the current checkout.
- Scope exclusions: `openspec/changes/archive/`, `CHANGELOG.md`, the submodule, lockfiles, and `.vulture_whitelist`, which is regenerated with `vulture --make-whitelist` instead of edited.

The active changes `benchmark-worker-fault-recovery` and `complete-native-coverage` are updated because their remaining tasks will execute against the new layout.

### D8. No dedicated layout check

The root-layout requirement is reviewed, not tested. A pytest that lists the root would duplicate what `git ls-tree` shows and would need edits for every legitimate addition. Conclusion: no validator; nothing further needed.

### D9. Performance

The library runtime is unaffected when the wheel's file list and Python sources match `main`, which the artifact comparison task checks. Test and lint execution change only through import paths and the narrower mypy and vulture roots of D3, which remove work; inspection suffices, and no benchmark is run.

## Risks / Trade-offs

- [Contributor commands from memory, shell history, or open branches use old paths] → Rebasing branches onto the move produces conflicts or stale imports that the test suite and mypy reveal; the PR description lists the path map.
- [An existing clone keeps a populated `specifications/` directory and a 2 GB `native/shared-index/target/` after pulling] → The PR description gives the one-time commands from the Migration Plan.
- [A path reference missed by the substitutions] → The verification task greps for every old path and allows only the D7 exclusions; local link checks run through `just lint`, and `just docs-build-editions` builds both editions.
- [Future top-level modules under `src/` escape mypy and vulture because of D3] → `src/` is the single distribution package's source root; a new top-level module there would change the package layout and would be reviewed with its tool configuration.

## Migration Plan

Merge as a series of commits that each leave the tree green (`tasks.md` order). After pulling, an existing clone runs once:

```bash
git submodule sync
git submodule update --init
```

Git leaves ignored and untracked files at the old paths: the previous submodule checkout in `specifications/`, Cargo output in `native/shared-index/target/`, raw reports in `reports/`, and caches or local files in the other moved directories. The contributor inspects each old directory, moves any local work it wants to keep to the corresponding D1 path, and only then deletes the directory.

Rollback: revert the commits; the reverse `git mv` restores the old layout and submodule path.
