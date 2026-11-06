# Design

## Context

`.github/workflows/publish.yml` runs on a pushed `vX.Y.Z` tag in this order: `build-and-verify` (an x86-64 and ARM64 matrix on GitHub-hosted runners, which uploads `dist-*` artifacts), then `prepare-github-release` (a draft), then `publish` (PyPI, inside the `pypi` environment with required-reviewer approval), then `publish-github-release`. Only `publish` holds `id-token: write`. The PyPI trusted publisher is bound to `publish.yml` and the `pypi` environment (`docs/development/pypi-publishing-setup.md`), so an OIDC token from any other job cannot upload to PyPI.

`pypa/gh-action-pypi-publish` already uploads PEP 740 _publish_ attestations by default. For 0.12.0, PyPI's integrity API reports predicate `https://docs.pypi.org/attestations/publish/v1`, publisher `publish.yml`, and environment `pypi`. That attestation proves who uploaded the file, but it carries no build provenance. It stays unchanged.

The repository is public, so GitHub artifact attestations are free and are signed through Sigstore's public-good instance, which records them in the Rekor transparency log. GitHub documents its artifact attestations as SLSA v1.0 Build Level 2 on their own, and as Build Level 3 only when the build runs in an isolating reusable workflow ([artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations)). The SLSA Build Level 3 "Isolated" requirement also forbids build-cache poisoning ([SLSA v1.2 build requirements](https://slsa.dev/spec/v1.2/build-requirements)). The release jobs here restore uv caches through `setup-toolchain` with `enable-cache: true`.

The stable documentation edition, which unversioned hosted URLs reach, is built from the latest published GitHub Release's tag. Content merged to `main` therefore appears only in the development edition until the next release.

## Goals / Non-Goals

**Goals:** see `proposal.md`.

**Non-Goals:**

- SLSA Build Level 3, the SLSA Source track, SBOM attestations, and an OpenSSF Scorecard badge. Each is a separate change if it is wanted.
- Provenance for releases that are already published.
- Verification at install time: neither pip nor uv verifies attestations.
- Changes to `release-verification.yml`, the build commands, or caching.

## Decisions

### D1. Target SLSA Build Level 2 (chosen by the user)

- **Build L2 with GitHub artifact attestations (chosen).** Pros: GitHub officially classifies it as L2; it adds one small job; the release build and its caches stay unchanged; ONNX uses the same setup in its `create_release.yml`. Cons: a lower badge level than L3.
- **Build L3 with a same-repository reusable workflow.** Pros: a higher badge level, and `publish.yml` and `release-verification.yml` could share one build definition. Cons: the build moves into a reusable workflow, and release builds must drop the uv cache. Users would also need a signer-workflow constraint that names the reusable workflow. The reusable workflow's signing job would require `id-token: write` from every caller, including the non-publishing verification workflow. The L3 claim rests on GitHub's reading of the spec: the provenance is still written by this repository's own workflow code, so a knowledgeable reviewer could dispute it, which works against the proposal's aim. Unknown: whether GitHub rejects a caller that does not grant `id-token: write` even when the signing job is skipped.
- **Build L3 with `slsa-framework/slsa-github-generator`.** Rejected. Its README has declared the project unmaintained since August 2026 and recommends GitHub artifact attestations instead. The last release was v2.1.0 in February 2025. The generator must be referenced by tag rather than by commit SHA, which conflicts with this repository's pinning policy.
- **Do not adopt SLSA.** Rejected: it would leave the proposal's aim unmet.

Conclusion: L2. No further research is needed. The L3 unknown is moot unless a future change pursues L3.

### D2. Generate provenance with `actions/attest`

- **`actions/attest` (chosen).** Pros: it is GitHub's maintained first-party action and generates the `https://slsa.dev/provenance/v1` predicate by default. Its output is stored in GitHub's attestation API and in Rekor, and users verify it with `gh attestation verify`. Cons: verification requires the GitHub CLI.
- **`actions/attest-build-provenance`.** Since v4 it is a wrapper around `actions/attest`, and its README directs new implementations to `actions/attest`. Rejected.
- **SLSA provenance uploaded to PyPI as PEP 740 attestations.** `gh-action-pypi-publish` generates only publish attestations, and it fails when a `.publish.attestation` file already exists. Uploading SLSA provenance would need custom tooling: one single-subject statement per file, plus a conversion from Sigstore bundles to the PEP 740 format. That conflicts with the AGENTS.md rule against reinventing tooling. Rejected.
- **Also attaching bundles as GitHub Release assets.** This would allow offline verification, but GitHub's API and Rekor already distribute the provenance, as SLSA's "Distribute provenance" requires. It would add a second copy that must be kept consistent. Rejected.

Conclusion: `actions/attest`. No further research is needed.

### D3. Sign in a dedicated job that runs no build steps

- **A dedicated job after the build (chosen).** Pros: build steps, including dependency build scripts and the PGO training run, never receive an OIDC token. Signing happens before the human approval gate, so the reviewer approves artifacts that are already attested. Cons: one extra short job per release. Provenance can also exist for a build that is later rejected or fails to publish, so provenance identifies a build of the publishing workflow, not a completed publication. D8 keeps that harmless, and the guide makes no publication claim.
- **Inside the build matrix.** Pros: no extra job. Cons: every build step could mint OIDC tokens and sign provenance for arbitrary files. Rejected.
- **Inside the `publish` job, as ONNX does.** Pros: that job already holds `id-token: write`. Cons: provenance is created only after approval, so the reviewer cannot see it, and duties mix inside the PyPI-privileged environment job. Rejected.

The provenance content does not depend on the job: it describes the workflow run, tag, commit, and the signing runner's environment. The job needs no checkout, so it gets no `contents` grant. `artifact-metadata: write` applies only to OCI storage records. Downloading artifacts from the same run uses the runtime token, as `publish` already does without `actions: read`. Conclusion: a dedicated job. No further research is needed.

### D4. Sign before the GitHub Release draft

- **Linear, with signing between the build and the draft (chosen).** Pros: a failed signing or verification step leaves no draft GitHub Release to clean up. Cons: the signing job's short runtime is added once per release, before a manual approval that already dominates latency.
- **Signing in parallel with the draft, with `publish` needing both.** Pros: it saves that short runtime. Cons: a failure leaves an orphaned draft. Rejected.

Conclusion: linear. No further research is needed.

### D5. Enforce the user-facing policy in the workflow

- **Verify the signing step's own bundle offline (chosen).** Pros: it checks the signature, the transparency-log inclusion, the subject digests, and every policy constraint users rely on. It does not depend on how quickly the attestation API exposes a freshly created attestation. Cons: it does not exercise the API lookup path that users take. A failed upload already fails `actions/attest`, and the first attested release exercises that path once ([issue #420](https://github.com/alessio-locatelli/client-query-cache/issues/420)).
- **Verify through the API lookup.** Pros: it matches the user path exactly. Cons: a propagation delay after creation is unknown and could fail a correct release. Rejected.
- **No in-workflow verification.** Pros: none beyond saving seconds. Cons: the attest action does not check the consumer policy, so the documented constraints could silently stop matching what releases satisfy, and users would discover it first. This is a check of a contract that no existing tool enforces, so it does not fall under the AGENTS.md rule against redundant validators. Rejected.

Conclusion: offline bundle verification. No further research is needed.

### D6. One verification policy

The constraints are listed in `specs/release-provenance/spec.md` ("Publication requires verifiable provenance"), and the exact command is in `tasks.md` task 1.1. Each constraint has a purpose:

- The repository constraint selects where the attestation is fetched and whose identity signed it.
- The signer-workflow constraint means that only release builds verify, even if another workflow ever signs something.
- The source-ref constraint lets users assert which version they hold. Together with D8, it identifies one commit.
- The hosted-runner constraint covers only the signing job. The build jobs' GitHub-hosted runners are guaranteed by the workflow definition at the named commit, which consumers can inspect ("Release builds run on GitHub-hosted runners"), and the guide says so.

The workflow repeats the repository and signer-workflow values as the same literals the guide uses, not as values derived from `GITHUB_REPOSITORY` or `GITHUB_WORKFLOW_REF`, because a derived value always matches the run that produces it. With literals, renaming the repository or the workflow fails the next release until the guide is updated. A shared script is not possible, because users do not have the repository.

### D7. Documentation placement and timing

- **Guide location: the installation guide.** Pros: it is hosted, versioned with release editions, indexed by Context7, and sits where users fetch the package. Cons: the installation page grows by one section, which is why that requirement's scope is modified. Alternatives: `.github/SECURITY.md`, as ONNX does, is not hosted or versioned; a new Operations page separates verification from installation. Both rejected.
- **The badge and the `SECURITY.md` link go in a commit made after the first attested release is published, and link the hosted guide (chosen).** Pros: both appear only once the newest release carries provenance and the unversioned hosted URL reaches a stable edition that contains the section, even if a release attempt fails under D8. Cons: the step happens after this change is implemented and is tracked in [issue #420](https://github.com/alessio-locatelli/client-query-cache/issues/420), and that release's PyPI page lacks the badge, which later releases carry. Alternatives:
  - Adding them at merge, or in the release's version-bump commit, would show the claim while the newest published release lacks provenance whenever that release has not been published yet or fails, and the link would reach a stable edition without the section. Rejected.
  - Linking the development edition would give a permanent link to unreleased documentation. Rejected.
  - Linking `https://slsa.dev`, as in the request's example, would give readers no path to the evidence; the guide links SLSA's level definition instead. Rejected.
- **`CONTRIBUTING.md` links the guide's repository source**, as its other documentation links do, so the link is valid on `main` immediately.
- **No Context7 rule.** Verifying provenance is not a library-usage mistake that a coding agent realistically makes, and `docs/user` is already indexed.
- **No `CHANGELOG.md` entry.** Under the editing policy, provenance alone would not warrant a package release; it concerns CI and release infrastructure.

Conclusion: as chosen. No further research is needed.

### D8. A release tag is spent once signing has started

If a tag were recreated at another commit after signing, the earlier build's provenance would still pass a source-ref check for that version.

- **Spent once the run reaches `actions/attest` (chosen).** Recovery from a failure before that step may recreate the tag, because no provenance exists for it. After that step has started, the fix ships under the next patch version. Pros: one tag always maps to one commit with provenance, and the user policy stays version-based. Starting the step, rather than finishing it, counts, because a signature may already be in Rekor when a later sub-step fails. Cons: a failure after signing consumes a version number that never reaches PyPI.
- **Allow tag reuse and add the expected commit (`--source-digest`) to the user policy.** Cons: users would have to look up the commit before every verification. Rejected.
- **Never recreate any pushed release tag.** Pros: a simpler rule. Cons: it consumes a version even for failures before any provenance exists. Rejected.
- **A tag ruleset blocking deletion of `v*` tags.** Pros: technical enforcement. Cons: it also blocks the safe pre-signing recovery, and it lives in repository settings outside review. Rejected.

This is a procedural invariant that the maintainer upholds. Neither the workflow nor the documented verification policy detects a moved tag, because the policy checks the tag name rather than the commit. The guide says so.

Conclusion: the maintainer procedure in `CONTRIBUTING.md` (task 1.3). No further research is needed.

### D9. Retire an incomplete PyPI upload under a new version

PyPI never accepts a filename twice. If PyPI accepted only some distributions, re-running `publish` therefore fails on the files it already accepted.

- **Yank the incomplete version and release the next patch version (chosen).** Pros: no workflow change and no credential outside Trusted Publishing, and normal uploads still fail on any existing file. Cons: a rare upload failure consumes a version number, and the yanked files remain installable through an exact version pin.
- **Enable `skip-existing` only on re-run attempts (`github.run_attempt > 1`).** Pros: it completes the same version. Cons: it changes the privileged upload path in a way that only a real partial failure exercises, and re-running all jobs would mix files from two builds under one version. Rejected.
- **Enable `skip-existing` for every upload.** Cons: normal releases would silently skip files that already exist. Rejected.
- **Upload the missing files manually with an API token.** Cons: this contradicts the release-publishing requirement that publication uses no stored credential. Rejected.

If PyPI accepted every file but `publish` reported a failure, the release is already complete on PyPI. Publishing the draft manually then finishes the release without another upload. A manual run of the documentation workflow replaces the stable-edition publication that the failed publish run no longer triggers.

Conclusion: the maintainer procedure in `CONTRIBUTING.md` (task 1.3). No further research is needed.

## Risks / Trade-offs

- [The first tagged run is the first live run of the signing job, and later bot updates of the pinned action are also first exercised by a release.] → Signing runs before the draft and the approval gate, so a failure publishes nothing. actionlint and zizmor (`just ci-lint`) check the workflow statically, and D8 bounds the recovery. `gh-action-pypi-publish` already carries the same live-only risk.
- [A GitHub, Sigstore, or Rekor outage during a release blocks publication.] → Re-run the failed jobs of the same run after the outage. The commit is unchanged, so a re-run does not conflict with D8.
- [Build Level 2 trusts this repository's workflow definition: anyone able to push a release tag can change how releases are built and still obtain valid provenance.] → This is inherent to L2, and the guide's "does not prove" text states it. The provenance names the exact commit, so its source and workflow are auditable.

## Migration Plan

1. Merge `tasks.md` groups 1 and 2. Nothing runs until the next tag push.
2. After the next published release, complete [issue #420](https://github.com/alessio-locatelli/client-query-cache/issues/420).
3. Recover from release failures with the `CONTRIBUTING.md` procedure (D8, D9).
4. Rollback: revert the workflow, the guide, the badge, and the `SECURITY.md` link together, so that the claim and the automation stay consistent. Existing attestations remain valid for the releases they cover.
