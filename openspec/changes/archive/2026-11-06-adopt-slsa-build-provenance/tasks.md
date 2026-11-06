# Tasks

## 1. Release workflow

- [x] 1.1 In `.github/workflows/publish.yml`, add a job `attest` named `Attest build provenance` (design D3). Give it `needs: build-and-verify`, `runs-on: ubuntu-24.04`, `timeout-minutes: 5`, and job-level `permissions` containing only `id-token: write` and `attestations: write`. It gets no checkout and no `setup-toolchain`. Steps, in order:
  1. `actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1` with `pattern: dist-*`, `merge-multiple: true`, `path: dist/`.
  2. `actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6 # v4.2.2` with `id: attest` and `subject-path: dist/*`.
  3. A `run` step with `env` set to `BUNDLE_PATH: ${{ steps.attest.outputs.bundle-path }}` and `GH_TOKEN: ${{ github.token }}`, running this command under the default `bash -e` shell. It is the single source of the policy flags (design D5, D6):

     ```bash
     for file in dist/*; do
       gh attestation verify "${file}" --bundle "${BUNDLE_PATH}" --repo alessio-locatelli/client-query-cache --signer-workflow alessio-locatelli/client-query-cache/.github/workflows/publish.yml --source-ref "${GITHUB_REF}" --deny-self-hosted-runners
     done
     ```

  Explain each behavioral override in the file's existing format ("The default is … We override it because …", with a version-specific reference URL), following `openspec/specs/development-environment/spec.md`. That covers the job permissions, the timeout, and the `--bundle`, `--signer-workflow`, `--source-ref` and `--deny-self-hosted-runners` flags. Use these references: `https://github.com/actions/attest/blob/1e69f48acb82d1966a394da916b4c1698aa569d6/action.yml` and `https://cli.github.com/manual/gh_attestation_verify`. For the download inputs, which repeat those of `publish`, either turn the existing `publish` download comment into a shared explanation that names both occurrences, or give the new step its own explanation. Verify that `uv run -- prek run actionlint --all-files` and `just ci-lint` report no findings, and that `git diff` shows no change to `build-and-verify`.

- [x] 1.2 Set `prepare-github-release` to `needs: attest` (design D4). Run this command:

  ```bash
  uv run -- python -c 'import yaml; jobs = yaml.safe_load(open(".github/workflows/publish.yml"))["jobs"]; [print(name, job["needs"] if "needs" in job else None, job["permissions"] if "permissions" in job else None) for name, job in jobs.items()]'
  ```

  Verify that the printed `needs` chain matches D4, and that `attest` is the only job whose permissions include `attestations`.

- [x] 1.3 In `CONTRIBUTING.md` § Releasing:
  - Update the paragraph that begins "Pushing the tag triggers the `publish.yml` workflow". It must say that after building and verifying, the workflow signs SLSA build provenance and checks it before creating the draft release, and link the guide with the repository-relative target `docs/user/getting-started/installation.md#verify-release-provenance`.
  - Add a `### Failed releases` subsection with the design D8 and D9 procedure. Before acting on any failure, check which files PyPI holds for the version at `https://pypi.org/pypi/client-query-cache/X.Y.Z/json` (HTTP 404 means none). Compare their filenames and `urls[].digests.sha256` values with the `sha256sum` of the run's artifacts, downloaded with `gh run download <run-id> --pattern 'dist-*'`:
    - (a) PyPI holds no file of the version, and the failure is a transient outage: re-run the failed jobs of the same run with `gh run rerun <run-id> --failed`. The tag and commit stay unchanged, so D8 allows this even after signing.
    - (b) PyPI holds no file, the failure needs a fix on `main`, and the run never reached the `attest` job's `actions/attest` step: delete the tag with `git push --delete origin vX.Y.Z` and `git tag -d vX.Y.Z`, fix the problem on `main`, repeat the per-release validation for the fixed commit, and tag it with the same version.
    - (c) PyPI holds no file, and the failure needs a fix on `main` or the approval was rejected after that step started: keep the tag, delete any draft with `gh release delete vX.Y.Z --yes` (which keeps the tag), fix the problem on `main`, and release the next patch version. Bump `pyproject.toml` and rename the unpublished `CHANGELOG.md` section to the new version and date.
    - (d) PyPI holds every distribution with matching filenames and digests: never re-run `publish`. If only `publish-github-release` failed, re-run it with `gh run rerun <run-id> --failed`. If `publish` itself reported failure, publish the draft with `gh release edit vX.Y.Z --draft=false`. Then start the documentation workflow with `gh workflow run docs.yml --ref main`, because it publishes the stable edition only after a successful publish run. Confirm with `gh run watch` that its deployment succeeds. Never delete the tag or the release.
    - (e) PyPI holds only some distributions, or any digest differs: never re-run `publish`, because PyPI rejects the filenames it already accepted (design D9). [Yank](https://docs.pypi.org/project-management/yanking/) the incomplete version on PyPI. Then keep the tag, delete the draft, and release the next patch version, as in (c).

  Verify that `rg -c -- '--cleanup-tag|gh attestation verify' CONTRIBUTING.md` prints nothing and that the link target exists after task 2.1.

## 2. Verification guide

- [x] 2.1 In `docs/user/getting-started/installation.md`, add `## Verify release provenance` after `## Install`, so that its anchor is `#verify-release-provenance` (design D7). The section contains:
  - One sentence stating that the source distribution and wheels of each release published after 0.12.0 carry signed [SLSA Build Level 2](https://slsa.dev/spec/v1.2/build-track-basics#build-l2) provenance created by GitHub Actions, and that 0.12.0 and earlier releases have none. Before writing it, confirm with `git tag --sort=-v:refname | head -1` that 0.12.0 is still the newest release tag, and use whatever is newest if it is not.
  - A console example: `pip download client-query-cache==X.Y.Z --no-deps -d dist`, then task 1.1's `gh attestation verify` invocation for `dist/client_query_cache-X.Y.Z-*.whl` without `--bundle`, with `--source-ref refs/tags/vX.Y.Z`.
  - A prerequisite note: the [GitHub CLI](https://cli.github.com/manual/gh_attestation_verify) must be signed in to a GitHub account with [`gh auth login`](https://cli.github.com/manual/gh_auth_login), even for this public repository ([cli/cli#11803](https://github.com/cli/cli/issues/11803)). No installation instructions.
  - What success proves: the file was signed by `publish.yml` for that tag and commit of this repository, on a GitHub-hosted signing runner, with the signature in a public transparency log. The workflow at that commit defines the GitHub-hosted build runners and can be inspected (design D6).
  - What it does not prove: that the code is free of defects or vulnerabilities, that the workflow and source at that commit are trustworthy, or that the tag was never moved to another commit. The release procedure, not verification, prevents moved tags (design D8).

  Verify by downloading that release's wheel to `/tmp/agents/slsa-verify/` and running the documented command. It must fail because no attestation exists for the file's digest, not with a flag-parsing or authentication error. Verify also that `just docs-build` succeeds.

## 3. Code Quality

- [x] 3.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization.
- [x] 3.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies), apart from the workflow override rationales that `openspec/specs/development-environment/spec.md` requires. OpenAI Codex is exempt from this rule because it understands the difference between garbage and valuable code comments.
