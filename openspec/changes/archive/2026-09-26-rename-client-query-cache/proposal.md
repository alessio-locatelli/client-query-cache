# Proposal

## Why

The repository name suggests a language-neutral MongoDB library, while the public API is a client-side cache built specifically around PyMongo. Give the repository, distribution, and import package one descriptive identity: `client-query-cache`.

## What Changes

- **BREAKING** Rename the Python distribution from `mongo-client-cache` to `client-query-cache` and the import package from `mongo_client_cache` to `client_query_cache`, including sync and asyncio public imports.
- Rename the repository from `mongodb-client-cache` to `client-query-cache` and update current project links, contributor tooling, CI, examples, and package metadata to match.
- Position the library as “Client-side caching for PyMongo, kept coherent using MongoDB change streams.” Document the changed install and import names for existing users.
- Keep historical benchmark evidence and archived change records identifiable without rewriting their recorded results.

## Capabilities

### New Capabilities

- `project-identity`: Consistent repository, distribution, import, and user-facing project identity, including migration guidance.

### Modified Capabilities

- `development-environment`: Build and locked-project requirements use the renamed source package and verify its installed imports.

## Impact

The rename touches `pyproject.toml`, `uv.lock`, `src/`, imports in tests and benchmarks, the installed-package check, README and migration guidance, contributor container names, CI, and project-owned identifiers in reports and schemas where appropriate. External consumers must update their dependency and imports. The GitHub repository rename is a separate rollout action after the repository content is ready.
