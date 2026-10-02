# Executable version updates

The official hosted Renovate app proposes monthly updates, with maintainer review
and a seven-day delay when release timestamps are available. MongoDB stays on
8.0 noble, Python on 3.14, and Node.js on 24.

| Selection                                                    | Owner                                      | Location                                                                                        |
| ------------------------------------------------------------ | ------------------------------------------ | ----------------------------------------------------------------------------------------------- |
| Manifest dependencies, action references, and hook revisions | Dependabot                                 | Existing supported manifests, `uses:` references, `.pre-commit-config.yaml`                     |
| CI uv and just                                               | Renovate `github-actions`, `uses-with`     | Literal inputs in `.github/actions/setup-toolchain/action.yml`                                  |
| CI Node.js                                                   | Renovate `github-actions`, `uses-with`     | `test.yml` `node-version`                                                                       |
| Python                                                       | Renovate `pyenv`                           | `.python-version`; uv and the container consume it; CI caches hash it                           |
| MongoDB                                                      | Renovate regex                             | `tests/conftest.py` and `benchmarks/stream_cost/topology.py`; one group                         |
| Prek                                                         | Renovate Dockerfile/GitHub Actions presets | `test.yml` `PREK_VERSION` and Containerfile ARG; one group; cache derives from the CI selection |
| Zizmor                                                       | Renovate Dockerfile preset                 | Containerfile ARG                                                                               |
| Taplo                                                        | Renovate regex                             | Containerfile ARG, download URL, and SHA256                                                     |
| DNF tools                                                    | Fedora repositories                        | Unpinned Fedora 44 packages, retaining Node.js 24; [rationale](../CONTRIBUTING.md#environment)  |

In this repository, Renovate's Actions manager updates only `uses-with` inputs.
Its other dependency types are disabled to preserve Dependabot ownership. Reports,
test data, local image labels, schema/project versions, and compatibility floors
are excluded.

The existing Prek job runs the official configuration validator. To run it locally:

```console
prek run renovate-config-validator --files renovate.json5
```

For inventory inspection, use the [official Renovate CLI](https://docs.renovatebot.com/getting-started/running/)
and its [local dry-run interface](https://docs.renovatebot.com/modules/platform/local/):

```console
LOG_LEVEL=debug renovate --platform=local --dry-run=extract
LOG_LEVEL=debug renovate --platform=local --dry-run=lookup
```

Compare enabled dependencies with the ownership table; extraction also lists
Actions dependencies whose updates are disabled. Inspect skipped entries and
warnings, including missing GitHub authentication, even if the CLI exits successfully.
The local platform is experimental and creates no update branches. Review proposed
diffs for coupled versions and Taplo URL/checksum consistency; CI checks their
consumers, including the container build and isolated MongoDB startup.

Administrators install the [official hosted app](https://docs.renovatebot.com/getting-started/installing-onboarding/)
after validation and inventory review. Repository configuration does not install it.
If container or benchmark-startup checks become required, also require their
`Select validation tiers`, `Prek`, and `Prettier, Markdownlint, and OpenSpec`
prerequisites independently: skipped downstream jobs can report success.
