## 1. Establish uv project management

- [ ] 1.1 Replace Poetry metadata, lockfile, and build backend with PEP 621 metadata, dependency groups, `uv_build`, and `uv.lock`; configure `[tool.uv.build-backend]` with `module-root = ""` for the flat `mongo_client_cache/` package; verify `uv sync --all-groups --locked` and `uv build` succeed.
- [ ] 1.2 Set the published dependency range to `pymongo>=4.13,<5`, align Python-version declarations and development dependencies with CPython 3.13+, and verify an environment pinned to PyMongo 4.13 imports `AsyncMongoClient` successfully.

## 2. Add local quality gates

- [ ] 2.1 Add pinned Prek hooks for hygiene, Ruff, Ruff-extra, Vulture, mypy, slotscheck, Prettier, and secret detection; replace the existing Poetry-specific project check with a local hook running `uv lock --check` with `pass_filenames: false`; verify the complete quality workflow invokes every hook and rejects an out-of-date `uv.lock`.
- [ ] 2.2 Configure the isolated Python 3.14 Ruff-extra hook without raising the package runtime floor; verify it runs while `requires-python` remains 3.13+.
- [ ] 2.3 Correct all existing quality findings and document narrow exclusions; verify the complete Prek run succeeds without broad suppressions.
