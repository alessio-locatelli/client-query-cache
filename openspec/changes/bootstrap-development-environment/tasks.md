## 1. Establish uv project management

- [x] 1.1 Replace Poetry metadata, lockfile, and build backend with PEP 621 metadata, dependency groups, `uv_build`, and `uv.lock`; configure `[tool.uv.build-backend]` with `module-root = ""` for the flat `mongo_client_cache/` package; verify `uv sync --all-groups --locked` and `uv build` succeed.
- [x] 1.2 Set the published dependency range to `pymongo>=4.18`, align Python-version declarations and development dependencies with CPython 3.14+, and verify an environment pinned to PyMongo 4.18 imports `AsyncMongoClient` successfully.

## 2. Add local quality gates

- [x] 2.1 Add pinned Prek hooks for hygiene, Ruff, Ruff-extra, Vulture, mypy, slotscheck, Prettier, and secret detection; replace the existing Poetry-specific project check with the official `astral-sh/uv-pre-commit` `uv-lock` hook run with `--check`; verify the complete quality workflow invokes every hook and rejects an out-of-date `uv.lock`.
- [x] 2.2 Configure the Ruff-extra hook to run under the CPython 3.14 package baseline
- [x] 2.3 Correct all existing quality findings and document narrow exclusions; verify the complete Prek run succeeds without broad suppressions.
