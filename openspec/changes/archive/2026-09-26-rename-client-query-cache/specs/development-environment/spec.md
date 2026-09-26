# Spec Delta

## MODIFIED Requirements

### Requirement: Contributors use a locked uv project

The repository SHALL use `uv` for dependency resolution, environments, and package builds, SHALL
configure `uv_build` with `module-root = "src"` for the
`src/client_query_cache/` package, SHALL commit `uv.lock`, and SHALL support CPython 3.14+. Its
published PyMongo dependency SHALL declare the lower bound required for the supported native async
API. The declared dependency metadata SHALL be the sole maintained source of that concrete lower
bound: the minimum-version validation SHALL resolve and exercise it without repeating a version in
tox, tests, or specifications. Published runtime dependencies SHALL NOT declare a speculative upper
bound: a dependency floor SHALL exclude only versions with a known, documented incompatibility,
never versions that merely do not exist yet, per [the standard guidance against pinning a library's
dependency ceiling](https://iscinumpy.dev/post/bound-version-constraints/#pinning-the-python-version-is-special).
Published runtime dependencies SHALL remain distinct from development tooling.

#### Scenario: A clean checkout is synchronized

- **WHEN** a contributor synchronizes all declared development groups with the locked command
- **THEN** the environment is created without changing the committed lockfile

#### Scenario: Source-layout distributions are built

- **WHEN** a contributor builds the project distribution
- **THEN** each resulting source and wheel distribution contains `client_query_cache` and imports
  successfully in a clean environment

#### Scenario: The minimum PyMongo version is exercised

- **WHEN** the project validates its declared PyMongo lower bound
- **THEN** it resolves the lower bound from the published dependency metadata, imports
  `AsyncMongoClient`, and runs the supported minimum-version checks successfully
