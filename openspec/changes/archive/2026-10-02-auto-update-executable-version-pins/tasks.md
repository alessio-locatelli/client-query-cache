# Tasks

## 1. Ownership and custom extraction

- [x] 1.1 Add `renovate.json5` with only `custom.regex` enabled, explicit file allowlists, monthly scheduling, seven-day minimum release age where available, no automerge, and the release-track rules in design.md. Preserve Dependabot ownership of existing manifests and FROM/Compose images. Verify configuration validation and extracted dependencies show no overlap.
- [x] 1.2 Annotate both MongoDB Python pins, all four CI uv pins, the just action input, Prek and Zizmor selections, `.python-version`, and the Node 24 selector using the chosen datasources. Match `.python-version` through an exact file-specific regex, without inserting comments that would break its consumer format; do not annotate the workflow Python selections removed by task 2.2. Group coupled occurrences and add configuration extraction/replacement cases demonstrating both MongoDB replacements, all CI uv replacements, and exclusion of `reports/`, test data, package release metadata, and compatibility floors. Verify the initial annotation diff changes no selected release.
- [x] 1.3 Add the concise ownership inventory and reproduction commands to contributor documentation, linking official Renovate onboarding guidance. Verify every executable occurrence in design.md is assigned once, including selectors that intentionally retain a major track; document administrator activation as an external deployment step, not an automatic repository-setting change.

## 2. Coupled toolchain and container pins

- [x] 2.1 Derive the Prek install and cache key from one named CI selection, keeping its Containerfile PyPI occurrence in the same Renovate update group. Add a replacement case verifying the new cache identity and both installs agree without a separate cache-key version pin.
- [x] 2.2 Read `.python-version` after checkout in the setup-toolchain composite action, pass the exact output to setup-uv, and expose it for workflow cache keys; remove the four workflow Python selections. Copy/read that file in the Containerfile installation RUN and remove the duplicate Python ARG. Preserve the 3.14 track and published floors; document that CI now selects the committed exact patch. Add scope/consumer cases proving each workflow and the container use the selected version; document the canonical selection in the contributor ownership inventory.
- [x] 2.3 Remove the DNF version ARGs for bash, just, nodejs24, nodejs24-npm, and uv and install those package names from Fedora 44 repositories. Retain the Node 24 package track and all non-DNF pins. Document the bot limitation, low expected development-tool breakage risk, and variable RPM versions across rebuilds; amend the development-environment pinning contract with this explicit exception. Container build/tool verification remains required by task 3.2.
- [x] 2.4 Add Taplo release-attachment extraction/replacement spanning its ARG, ADD URL, and SHA256. Add successful replacement and unavailable/mismatched digest cases; verify a candidate build preserves the compressed linux-x86_64 artifact, checksum verification, and expected `taplo --version`. Keep diagnostic raw output untracked and document the reproduction command.

## 3. Consumer validation

- [x] 3.1 Extend `scripts/ci_scope.py` and `.github/workflows/test.yml` with container and isolated-benchmark scopes and route `.python-version` and shared Python-tool inputs into the Python gates. Add parametrized path-selection cases covering each managed input and unrelated documentation; verify no pin-only update bypasses its consumer checks.
- [x] 3.2 Add development-container build/tool smoke checks and a bounded isolated benchmark replica-set startup check after applicable lint/format jobs. Verify a Containerfile-only replacement builds and checks installed tools, a MongoDB-only replacement runs integration/e2e plus startup validation, and unrelated documentation triggers neither added expensive check. Preserve stable required-check identities and document any administrator ruleset prerequisites.
- [x] 3.3 Adapt guard environment preparation to use the proposed selected interpreter for both revisions when guarded inputs change alongside Python. Add behavior cases proving equal interpreters, retained mismatch rejection, and visible failure when the base cannot run. Verify guard evidence records the actual interpreter without exempting bot PRs.

## 4. Coverage and activation evidence

- [x] 4.1 Produce a concise Markdown extraction/replacement proof with reproducible commands and the complete ownership inventory, including the explicit unpinned Fedora package exception and Taplo digest results. Demonstrate no uncovered executable selections, no overlap with Dependabot, unchanged historical evidence, and visible lookup failures. Keep raw registry responses and dry-run logs untracked; activate Renovate only through the documented administrator step after this proof is complete.

## 5. Code Quality

- [x] 5.1 Scan every file containing edited or added tests, including pre-existing tests in those files, and apply AGENTS.md Writing Tests guidelines, including parametrization; verify the resulting test diff follows those rules.
- [x] 5.2 Claude Code prose restriction is inapplicable: this proposal is prepared by OpenAI Codex; Codex is exempt.
