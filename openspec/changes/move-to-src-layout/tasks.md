## 1. Move the distributable source tree

- [ ] 1.1 Move `mongo_client_cache/` to `src/mongo_client_cache/` with Git-aware renames and
      verify every production module retains its path below the public package namespace.
- [ ] 1.2 Set `uv_build` to the `src` module root, update Vulture and the coverage exclusion scan
      to target `src/mongo_client_cache`, and verify no tracked configuration or command still relies
      on the root production-package path.
- [ ] 1.3 Remove tox's `--import-mode importlib` overrides and verify each tox test command uses
      pytest's default import mode while the non-editable wheel remains its production import source.
- [ ] 1.4 Replace the exact PyMongo pin in the minimum-version tox environment with metadata-driven
      lowest-direct resolution and verify it resolves the lower bound declared by `pyproject.toml`.
- [ ] 1.5 Verify `uv lock --check` succeeds without changing `uv.lock`, since the source-root
      configuration does not affect dependency resolution.
- [ ] 1.6 Update the CI package-install validation to install and import each built source and wheel
      distribution in separate isolated environments.

## 2. Validate the package boundary

- [ ] 2.1 Build source and wheel distributions and verify isolated interpreters import each
      artifact's public `CacheManager`, `CachedCollection`, and `CachedDatabase` API.
- [ ] 2.2 Run the documented formatting, quality, and unit-test recipes and verify they pass with
      the editable `src` installation.
- [ ] 2.3 Run the `py314` tox environment and verify its default-import-mode unit suite passes
      against the non-editable installed wheel.
- [ ] 2.4 Run the `pymongo-min` tox environment and verify the installed PyMongo version equals
      the declared direct-dependency lower bound and exposes `AsyncMongoClient`.
- [ ] 2.5 Run the documented end-to-end and coverage gates where the container runtime is
      available, and verify the moved production path remains fully measured and the clean-wheel
      harness succeeds.
