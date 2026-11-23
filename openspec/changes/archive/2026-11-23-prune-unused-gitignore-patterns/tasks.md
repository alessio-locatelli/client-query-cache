# Tasks

## 1. Remove unused ignore rules

- [x] 1.1 Apply the removal criteria in `design.md` to `.gitignore`. Review `git diff -- .gitignore` for unsupported entries, obsolete comments, and unintended changes to retained rules.
- [x] 1.2 Copy the revised `.gitignore` into an empty Git repository under `/tmp/agents/`, using `git init --template=` and `git -c core.excludesFile=/dev/null check-ignore -q --no-index -- <path>` for each probe. Expect status `0` for representative paths from each retained rule group in the design, including synthetic `.env`, `.agents/local.md`, `.claude/local.md`, and generated reports. Expect status `1` for former targets such as `docs/_build/index.html`, `.spyproject`, and `.pyre/cache`, as well as `.env.example`, `.agents/skills/.openspec-target`, `.agents/skills/openspec-propose/SKILL.md`, `.claude/settings.json`, and `.claude/skills/openspec-propose`.

## 2. Code Quality

- [x] 2.1 For each test file edited or added during implementation, review the entire file against the `Writing tests` guidelines in `AGENTS.md`, including parametrization.
- [x] 2.2 If applying with Claude Code, inspect the diff for new prose in code and put explanations in the specifications or commit body. Skip this check when applying with OpenAI Codex.
