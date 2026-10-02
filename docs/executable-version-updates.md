# Executable version updates

Dependabot manages supported manifests. Renovate handles the remaining exact
selections with file-specific custom regex managers. Updates require review,
run monthly, and wait seven days where the source supplies release timestamps.
MongoDB stays on 8.0 noble, Python on 3.14, and Node.js on 24.

| Selection                                    | Owner                                   | Occurrences / consumer                                                                                                                     |
| -------------------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Python MongoDB image                         | Renovate, Docker                        | `tests/conftest.py`, `benchmarks/stream_cost/topology.py`; one group                                                                       |
| CI uv                                        | Renovate, PyPI                          | `UV_VERSION` in test, publish, release-verification, and stream-cost-benchmark workflows; one group                                        |
| Prek                                         | Renovate, PyPI                          | `test.yml` `PREK_VERSION`, `Containerfile` `PREK_TOOL_VERSION`; one group; install and CI cache derive from the selection                  |
| just action input                            | Renovate, GitHub releases               | setup-toolchain `just-version`                                                                                                             |
| Python                                       | Renovate, Python versions               | `.python-version`; the composite action and container read the exact patch; workflow caches use the action output                          |
| Renovate proof runner                        | Renovate, Docker                        | `test.yml` `RENOVATE_IMAGE`; official image with exact tag and digest for pin-related changes                                              |
| Node.js CI selector                          | Renovate, Node versions                 | `test.yml` `node-version`; retains the major selector                                                                                      |
| Zizmor                                       | Renovate, PyPI                          | `Containerfile` `ZIZMOR_TOOL_VERSION`                                                                                                      |
| Taplo                                        | Renovate, release attachments           | `Containerfile` ARG, compressed linux-x86_64 URL, SHA256, and build version check                                                          |
| DNF tools                                    | Fedora repositories, unpinned exception | `bash`, `just`, `nodejs24`, `nodejs24-npm`, `uv`; Fedora 44, Node.js 24 package track; see [the rationale](../CONTRIBUTING.md#environment) |
| Base image and Compose images                | Dependabot, Docker                      | Containerfile FROM digest and Compose image versions/digests                                                                               |
| Python manifests and lock                    | Dependabot, pip/uv                      | `pyproject.toml`, `uv.lock`, inline script dependencies                                                                                    |
| npm manifests and lock                       | Dependabot, npm                         | `package.json`, `package-lock.json`                                                                                                        |
| Hook revisions, including uv and Taplo hooks | Dependabot, pre-commit                  | `.pre-commit-config.yaml`; independent from CI/container tools                                                                             |
| Action revisions                             | Dependabot, GitHub Actions              | workflow and composite action `uses` revisions                                                                                             |

Reports, test data, schema/project versions, local image labels, and compatibility
floors are excluded from custom extraction. DNF packages follow repository versions
at build time, so rebuilds can select different RPM revisions.

## Reproduce extraction and replacement checks

Pin-related changes run the proof in the existing formatting job before consumer checks.
The proof uses Renovate itself, not a second regex engine. It checks 14 extracted
occurrences, coupled MongoDB/uv/Prek values, consumers of the shared selections,
Taplo version/URL/digest replacement, and excluded paths. Replacement writes go to
a temporary directory. Missing tooling or a missing occurrence exits with an error.

Install Renovate in a disposable directory using its [official CLI guidance](https://docs.renovatebot.com/getting-started/running/),
then pass the installed package directory:

```console
npm install --prefix /tmp/executable-pin-renovate --registry=https://registry.npmjs.org --no-audit --no-fund renovate@44.132.2
node /tmp/executable-pin-renovate/node_modules/renovate/dist/config-validator.js renovate.json5
node scripts/check_executable_pins.cjs /tmp/executable-pin-renovate/node_modules/renovate
```

The recorded extraction proof uses Renovate 44.132.2. Its stock attachment lookup
returns no digest when the candidate lacks the mapped asset; an unrecognized
current digest can remain unchanged. A replacement cannot be accepted on extraction
alone: the image build checks the compressed artifact against SHA256 and checks
`taplo --version`. A missing, stale, or mismatched checksum must fail validation.
Keep registry responses, candidate definitions, and verbose logs untracked.

## Validate consumers

```console
bash scripts/check_dev_container.sh flatpak-spawn --host podman
uv run -- pytest -q tests/benchmark/stream_cost/test_topology_integration.py --timeout=120
just tests_and_coverage
```

Use `docker` or `podman` as the script's runtime argument when available directly.
The build script sends only Containerfile and `.python-version` into the build
context and checks package availability, the Node.js major, and exact Python,
Prek, Taplo, and Zizmor versions.

Container inputs trigger the container check. MongoDB inputs trigger database-backed
tests and bounded isolated benchmark startup. Shared Python/toolchain selections
trigger Python validation. Documentation alone triggers neither new consumer job.
The performance guard installs the proposed revision's Python selection in both
revision environments, records both actual versions, and rejects mismatches or
failed base installation.

## Repository administration

Administrators enable Renovate through its [official onboarding process](https://docs.renovatebot.com/getting-started/installing-onboarding/)
only after the extraction, replacement, and consumer proofs are complete. Repository
configuration does not install the app or change repository settings.

Keep the existing required-check names. If the new container and benchmark-startup
checks become required, also require `Select validation tiers`, `Prek`, and
`Prettier, Markdownlint, and OpenSpec` independently. A downstream job skipped after
a failed prerequisite can report success, so its prerequisite must block merging.

## Recorded consumer proof

The selected contributor image built through the host Podman bridge and passed all
tool checks. A published Taplo 0.9.3 artifact also built with its matching SHA256 and
reported the expected version; a deliberately wrong checksum was rejected. This
older available release exercises replacement mechanics without changing the
committed 0.10.0 selection. Reproduce it by making a disposable copy of the two
build inputs, substituting the ARG and URL, and using `sha256sum` on the downloaded
compressed artifact before running the same build checker; a wrong checksum must
produce a nonzero exit.

Both MongoDB pins were temporarily replaced with `8.0.5-noble`, and
`just pytest -- -q -m "integration or e2e" --timeout=120` passed, including isolated
benchmark startup. The committed `8.0.4-noble` selections were restored. Public
PyPI lookups for uv, Prek, and Zizmor, the just release lookup, and the Node.js 24
release index resolved the selected tracks. Raw lookup responses and test/build
logs remain outside version control.
