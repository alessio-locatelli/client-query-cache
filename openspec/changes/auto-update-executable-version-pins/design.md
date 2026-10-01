# Design

## Context

See [proposal.md](proposal.md) for motivation. `.github/dependabot.yml` already schedules monthly pip, uv, npm, pre-commit, GitHub Actions, and Docker updates with seven-day cooldowns. GitHub documents supported manifests, but no arbitrary-source custom manager; its Docker parser reads Dockerfile FROM declarations and YAML image fields, not Python literals or tool ARGs. See [supported ecosystems](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories) and [Docker parser](https://github.com/dependabot/dependabot-core/blob/main/docker/lib/dependabot/docker/file_parser.rb).

Current unsupported executable occurrences are:

| Input                                       | Location                                                       | Coupling / release policy                                                            |
| ------------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| MongoDB 8.0.4-noble                         | `tests/conftest.py`, `benchmarks/stream_cost/topology.py`      | Both use 8.0 noble; Compose independently uses 9.0 with a digest                     |
| uv 0.12.19                                  | Four `.github/workflows/*.yml` files                           | Shared CI tool; Containerfile uv is a Fedora RPM with a different version            |
| Prek 0.5.2                                  | `test.yml` install and cache key; Containerfile ARG            | Same PyPI release                                                                    |
| just 1.57.0                                 | setup-toolchain action input                                   | GitHub release; Containerfile just is independently packaged by Fedora               |
| Python 3.14.6 / CI 3.14                     | `.python-version`, Containerfile ARG, four workflow selections | Preserve 3.14 track and package compatibility floor                                  |
| Node 24                                     | `test.yml` action input                                        | Preserve Node 24 track; Fedora Node/npm have independent package revisions           |
| bash, just, nodejs24, nodejs24-npm, uv RPMs | Five Containerfile ARGs                                        | Fedora 44, full epoch/version/release; Node and npm must remain installable together |
| Zizmor 1.30.0                               | Containerfile ARG                                              | PyPI version                                                                         |
| Taplo 0.10.0                                | Containerfile ARG, ADD URL and SHA256                          | One release artifact and expected version                                            |

`scripts/ci_scope.py` currently misses Containerfile and `.python-version`. The performance guard rejects differing Python versions between revision environments; preserve this invariant. Existing development-environment specs require explicit tool versions and a base-image digest. Historical `reports/stream-cost/` inputs are evidence, not update targets.

## Goals / Non-Goals

**Goals:** Make unsupported executable selections discoverable and replaceable without another general-purpose bot managing existing manifests. Keep pin changes reviewable, installable, and covered by their actual consumers.

**Non-Goals:** Unify Fedora RPM versions with upstream tool releases, upgrade MongoDB release lines during onboarding, raise published Python/PyMongo floors, regenerate historical reports, alter cache runtime behavior, or automatically merge updates.

## Decisions

### 1. Keep ownership disjoint

Dependabot retains all existing supported manifests, including Compose images and the Containerfile FROM digest. Renovate uses only `custom.regex` with exact file allowlists and annotated occurrences; disable all built-in manifest managers. Group the two Python MongoDB occurrences, CI uv occurrences, Prek occurrences, and Taplo occurrences by dependency and track. The pre-commit uv hook remains an independent Dependabot-owned hook revision, not part of the CI installer group.

Use a small `renovate.json5` and adjacent `# renovate:` annotations with datasource, dependency name, and explicit versioning where needed. Match whole named assignments or action inputs, not arbitrary dotted numbers. Preserve the existing literal values when adding annotations. Alternatives: converting MongoDB to Compose solves that one gap but does not cover CI/RPM pins; a custom scheduled updater would duplicate release lookup, version ordering, PR lifecycle, and integrity handling. Replacing Dependabot conflicts with the selected preference.

### 2. Use upstream-specific sources and track constraints

Use Docker datasource for Python MongoDB image references, PyPI for uv/Prek/Zizmor, GitHub releases for just, and Python/Node version datasources for interpreter selections. Allow stable updates within MongoDB 8.0 noble, Compose's existing independent track, Python 3.14, Node 24, and Fedora 44. Upstream standalone tools can propose stable releases across version boundaries subject to review. Configure monthly Renovate scheduling and seven-day minimum age where the datasource supplies timestamps. Disable automerge, lockfile maintenance, and unrelated onboarding presets.

Python: make `.python-version` the exact executable selection consumed by CI setup and container build. After checkout, the setup-toolchain composite action reads the file in a shell step, passes that output to setup-uv, and exposes the selected version as an action output for cache keys. All four workflows remove their Python input/env duplication and consume that output. The Containerfile copies `.python-version` into the build context and reads it inside the existing installation RUN for Python and Python-tool installation, removing its separate Python ARG. CI therefore changes from latest available 3.14 patch selection to the exact committed patch; subsequent patch updates arrive as reviewed proposals. Do not rewrite `requires-python` or formatter/type-checker targets: they declare compatibility or syntax baselines. For Node, retain the existing major selector and constrain updates to that major; the exact Fedora package is separately maintained.

RPM: use Renovate's [RPM datasource](https://docs.renovatebot.com/modules/datasource/rpm/) and [RPM versioning](https://docs.renovatebot.com/modules/versioning/rpm/) against Fedora 44 release/update repository metadata for the build architecture. Group Node/npm proposals and verify the DNF transaction. Do not equate an upstream release with a Fedora package. The datasource documentation describes version-release values but does not guarantee epoch preservation or architecture selection: a focused fixture and lookup proof for `1:24.18.0-1.fc44` and `1:11.16.0-1.24.18.0.1.fc44` is required before activation. Use architecture-specific Fedora 44 release/update repositories, accepting only the intended architecture and noarch. If the stock datasource cannot preserve epochs or exclude incompatible architectures, stop the RPM implementation and report a full-coverage activation blocker. Do not add an unreachable repository helper as a custom datasource. A self-hosted deployment or a separately served normalized feed would be a new infrastructure decision requiring a revised proposal and user choice. No host package installation is involved.

### 3. Treat derived values as part of the update

Prek installation and cache identity must derive from one named version value in the workflow, rather than requiring a separate cache-key regex. CI uv pins may similarly be read from one repository-owned selection or matched as a grouped set; verify the resulting consumers, not merely equal replacement counts.

Taplo uses a multiline custom match with `currentValue` and `currentDigest` plus replacement of the ARG, URL version, and checksum. Renovate's [release-attachment datasource implementation](https://github.com/renovatebot/renovate/blob/main/lib/modules/datasource/github-release-attachments/index.ts) maps a known asset digest to the corresponding new release asset. Use that datasource for `tamasfe/taplo` and preserve the linux-x86_64 compressed artifact. Prove version/digest replacement together; a build must still enforce ADD checksum verification and the tool-version check. A null, unchanged-but-invalid, or unresolved digest is a blocked update, not grounds to remove verification.

### 4. Validate changed consumers

Extend CI scope with separate outputs for development-container inputs and isolated benchmark startup, while routing `.python-version` and shared Python-tool inputs into package and owned-runtime test validation. Keep basic checks first and expensive checks parallel after them. Containerfile changes trigger a container build and pinned-tool smoke verification; both bots' updates use this same path. MongoDB changes trigger integration/e2e tests and a bounded isolated replica-set startup check, without rerunning full benchmark matrices.

Use the proposed executable Python for both base and head performance environments when a Python update also changes another guarded input. Record the selected interpreter in guard evidence, keep the mismatch rejection, and fail visibly if the base cannot run on it. The guard must not compare different Python versions or exempt bot PRs. No change to the performance spec is needed: matched runs and reported measurement failure already require this behavior.

### 5. Make extraction coverage reproducible

Add a compact inventory of expected file/assignment occurrences, owners, and exclusion categories beside focused updater configuration checks. Check actual Renovate extraction and representative replacement output with fixture registry responses, including a missing checksum, RPM epoch, coupled Prek values, and unchanged report data. Do not add tests of internal helpers in `tests/`; exercise configuration and consumer behavior. Store only a concise proof and reproduction commands in contributor documentation; keep raw dry-run logs untracked.

## Risks / Trade-offs

- Two bots require precise ownership → Renovate has an explicit manager and file allowlist; extraction checks reject overlap and uncovered executable pins.
- Fedora metadata can be large and timestamps are unavailable → cache lookups, select only Fedora 44 repositories, use the stock streaming datasource only after the required epoch/architecture proof, and rely on monthly proposals plus build verification rather than claiming cooldown enforcement.
- Coupled package availability or checksum resolution can block a candidate → retain visible lookup/build failures; do not relax pinning or integrity checks.
- Docker image changes alter benchmark conditions → record actual versions in new runs and keep historical evidence unchanged.
- Newly added input files can bypass existing path gates → enumerate consumers and add scope regression cases for each managed input.
- Shared interpreter selection changes guard preparation → use one interpreter for both revisions and preserve failure reporting when measurement is unavailable.

## Migration Plan

1. Add non-RPM annotations/configuration and replace derived duplicate values without upgrading initial release tracks. Implement scope checks and the focused extraction/replacement proofs. Leave RPM update annotations absent until the stock-datasource proof passes.
2. Prove stock RPM epoch/architecture behavior against real upstream metadata, then add RPM annotations only if it passes. If it fails, stop full-coverage activation and request a revised infrastructure decision. Prove Taplo digest replacement, build the development image, and exercise MongoDB consumers under candidate replacements before claiming complete coverage.
3. Document the ownership table and official Renovate installation link in contributor documentation. Repository administrators enable Renovate only after extraction proves the intended scope; no bot installation or repository setting mutation is authorized by this planning request.
4. Roll back by disabling Renovate for this repository and reverting its config/annotations and consumer wiring. Dependabot retains its existing manifest ownership throughout.
