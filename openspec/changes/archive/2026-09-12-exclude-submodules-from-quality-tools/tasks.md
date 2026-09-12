## 1. Configure the repository-owned tooling scope

- [x] 1.1 Audit `justfile`, `.pre-commit-config.yaml`, `ruff.toml`, `mypy.ini`, `package.json`,
      `.markdownlint-cli2.jsonc`, `pytest.ini`, `tox.ini`, and CI for formatter, validator, linter,
      and pytest invocations that can encounter `specifications/`.
- [x] 1.2 Configure each applicable tool through its native configuration or repository-owned input
      scope, and remove redundant source-path arguments from root recipes.

## 2. Document and validate the boundary

- [x] 2.1 Add a concise contributor note that identifies `specifications` as separately tooled
      content.
- [x] 2.2 Run `just format`, `just lint`, and `just ci-lint`; confirm the submodule remains clean.
