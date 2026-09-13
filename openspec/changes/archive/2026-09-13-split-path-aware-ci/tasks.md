## 1. Split quality and formatting validation

- [x] 1.1 Add an always-on Prek workflow that skips only the Prettier hook; verify it retains the existing
      Python-tooling setup and full-tree Prek selection.
- [x] 1.2 Add a path-filtered Prettier and Markdownlint workflow for configured Prettier file types and
      formatter configuration; verify it runs the former local formatter-hook command directly.

## 2. Scope Python validation

- [x] 2.1 Add a Python-validation workflow triggered only by Python files, `pytest.ini`, `pyproject.toml`,
      and `uv.lock`; verify it runs the existing package-artifact and Docker-backed coverage checks in parallel.
- [x] 2.2 Remove the monolithic CI workflow and its classifier; verify the workflow configuration and strict
      OpenSpec change validate successfully.
