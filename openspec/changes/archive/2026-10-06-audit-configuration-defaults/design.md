# Design

## Context

See [proposal.md](proposal.md) for motivation and the [development-environment delta](specs/development-environment/spec.md) for the contract. The existing dependency-update specification already forbids restating inherited Renovate defaults; the contributor policy can extend that principle without changing update policy.

The checkout selects Zensical 0.0.68 in `uv.lock`. Its installed `zensical/config.py` initializes `invalid_links` and `invalid_link_anchors` to `True` and `site_dir` to `site`, matching explicit entries in `zensical.toml`. [Official validation guidance](https://zensical.org/docs/setup/validation/) agrees. These are confirmed cleanup candidates.

Other observed candidates require context-specific classification rather than immediate deletion:

- `justfile` exports `UV_LOCKED=1` and also passes `--locked` in several recipes. [uv documents their equivalence](https://docs.astral.sh/uv/reference/environment/#uv_locked); commands invoked outside just must be considered separately.
- `mypy.ini` combines `strict=True` with individual strictness settings. The installed mypy version's strict expansion determines which settings are redundant.
- `.pre-commit-config.yaml` includes `fail_fast: False` and an empty hook `args` list. Hook-provided arguments and Prek behavior determine whether omission is equivalent.
- `renovate.json5` sets `timezone` to `Etc/UTC` and a MongoDB rule's `pinDigests` to `false`. [Renovate's option reference](https://docs.renovatebot.com/configuration-options/) gives built-in defaults of `null` and `false`, respectively, but [the selected best-practices preset](https://docs.renovatebot.com/presets-config/#configbest-practices) enables Docker digest pinning. The MongoDB rule must be compared with that inherited baseline, and timezone omission must be checked against hosted schedule evaluation.
- `scripts/build_versioned_docs.py` sets `commit.gpgsign=false` in a disposable repository. A user's global Git configuration can otherwise affect that invocation; a matching built-in default alone does not establish redundancy.

## Goals / Non-Goals

**Goals:** Use the inventory below as the audit boundary and keep explanations maintainable beside their owning configuration or command examples.

**Non-Goals:** Change public Python defaults, redesign pipelines, alter live settings, upgrade dependencies to make cleanup possible, or introduce a generic default-detection checker.

## Decisions

### 1. Audit all owned tool surfaces using a bounded inventory

| Group                                  | Owned surfaces                                                                                                                                                                                                                                                                              |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A: Documentation and update automation | `zensical.toml`, `stable-docs.toml`, `lychee.toml`, `context7.json`, `renovate.json5`, `.github/dependabot.yml`                                                                                                                                                                             |
| B: Quality, packaging, and testing     | `pyproject.toml`, `ruff.toml`, `mypy.ini`, `pytest.ini`, `tox.ini`, `.coveragerc`, `.pre-commit-config.yaml`, `.gitlint`, `.taplo.toml`, `_typos.toml`, `.markdownlint-cli2.jsonc`, `.github/actionlint.yaml`, `package.json`, `.gitattributes`, `.gitignore`, `.prettierignore`            |
| C: Automation and runtime bootstrap    | `justfile`, `.github/workflows/*.yml`, `.github/actions/setup-toolchain/action.yml`, `Containerfile`, `docker-compose.yaml`, `scripts/*.py`, `scripts/*.sh`, and command/configuration builders used for disposable MongoDB in `tests/conftest.py` and `benchmarks/stream_cost/topology.py` |
| D: Other owned occurrences             | Additional tracked configuration or automation discovered by the scoped scan, including executable command examples in contributor/tooling documentation and flags in other benchmark orchestration modules                                                                                 |

Use `git ls-files` to enumerate tracked candidates, plain-text search for options/flags, and structural navigation for command builders. Apply the delta's “Behavioral overrides are distinguished from project inputs” requirement when classifying retained settings, including environment-controlled options. Declarative inputs remain candidates for removing proven redundancies, but do not automatically become rationale entries. Required project identity, version/checksum metadata, regex patterns, action identifiers, and operands are not overrides merely because they appear in configuration. Definitions of application or Python function defaults are outside this tool-invocation audit.

Exclude submodule contents, symlinks, generated output, lockfile contents as editing targets, historical reports, archived changes, agent skill bundles, and illustrative test fixtures. Lockfiles remain evidence for selected tool versions. Sensitive files, including `.env`, `.env.example`, and `.secrets.baseline`, are not read or edited by this audit; credential references in ordinary workflows remain in scope.

The alternative of restricting the audit to the named examples costs less initially but misses equivalent problems elsewhere. Its coverage limitation is already established; no prototype or further research is needed. A scan of every Python default would greatly expand scope into application design without improving tool configuration clarity; no further research is needed for rejecting it.

### 2. Compare behavior with only the candidate occurrence omitted

Establish the selected version from lockfiles, action SHAs, hook revisions, and tool pins. Read official version-matched docs/help/schema/source. For hosted tools or Fedora-provided tools without an exact runtime pin, record the documented/tested version and relevant execution context rather than claim a frozen default. Resolve relevant preset chains, wrapper exports, hook defaults, command precedence, and inherited Git settings before classifying an occurrence.

Use a temporary working audit ledger with file/key or command, classification, supplied value, omitted behavior, authoritative evidence, context, and removal or rationale destination where applicable. Ordinary retained project inputs need only a classification; they require no default research or explanation. Keep it untracked; transfer removal evidence to implementation commit bodies before delivery under the delta's traceability requirement. Group removals sharing evidence and context into concise prose entries rather than retain a permanent duplicate inventory. An unresolved comparison for a removal or behavioral override blocks completion, as specified in the delta.

Comparing only built-in default tables is faster but fails the Renovate and Git examples above. No further research is needed to reject that approach. Building a universal checker would require tool-specific semantic resolution and maintain a second configuration model. Existing official validators remain appropriate for syntax and supported options, with review enforcing the rationale policy; no prototype is needed.

### 3. Give each explanation one maintained home

Keep each rationale beside its setting or command. Shared comments may cover enumerated occurrences within the same owning file; command examples use adjacent explanations in their own guide. Strict JSON uses existing contributor documentation, with the npm options in `CONTRIBUTING.md`. Do not maintain a separate cross-file inventory. Retain authoritative version/context evidence and the delta's rationale sentence format, distinguishing behavioral policy from ordinary project inputs.

Critical privileged CI pins continue to use only the locations allowed by their exception; the implemented pins remain inline. Keep the contributor and agent pointers to the canonical development-environment requirements current. Purely contributor-facing comparisons for published command examples may use adjacent Markdown comments so public guides retain their high-level presentation.

Locality lets a future editor see the reason while changing the option. Concise repetition across independently edited files is preferable to a remote explanation that enumerates their implementation details. Within one file, share a comment only when default, context and rationale agree. Commit bodies remain the evidence home for removed defaults.

### 4. Detect upstream contract changes through real integrations

The delta's integration-test requirement and critical privileged CI pin exception define upgrade protection.

`openspec/specs/public-library-documentation/spec.md` already requires strict-build failures for missing pages and headings. `tests/test_build_versioned_docs.py` exercises real builds through `assemble`, but `release_repo` explicitly enables both validation settings. Its `failed_edition` fixture covers a missing heading and a missing source-layout file; the latter is not a missing-link-target test. The targeted changes are defined in task 1.3; historical release snapshots remain outside this disposable fixture.

`scripts/ci_scope.py` selects Python tests and documentation builds for `pyproject.toml` or `uv.lock` changes; `.github/workflows/test.yml` synchronizes all groups and runs `just tests_and_coverage`. The existing path therefore exercises these real-tool tests for documentation dependency updates without an additional job or workflow edit. They remain in the existing non-MongoDB test lane despite testing an external tool integration.

Explicitly repeating important defaults can preserve those settings across an upstream change, but adds configuration noise and cannot cover other upstream behavior changes. Integration tests cost build time and cover only exercised contracts, but verify the outcome the repository actually needs. No prototype or further design research is needed; the concrete coverage gap is assigned to task 1.3.

The same review applies to workflows and actions through task 3.2. `publish.yml` publishes to PyPI and changes GitHub releases; `docs.yml` deploys to Pages; `dependency-automerge.yml` approves and requests merging of eligible PRs. These effects explain why running the complete production workflow cannot be used as an audit experiment. Prefer an existing disposable execution path that exercises the relevant action or platform behavior without live publication, production credentials, or trust-boundary changes. Static inspection and mocked commands are useful analysis, but cannot establish real platform behavior.

Where such a path cannot adequately exercise a critical contract, use the delta's pin exception and record its assessment in the ledger. Blanket exemptions for workflow files would leave ordinary settings unaudited; forcing a production run would create unnecessary risk. The per-setting assessment costs review effort while allowing safe coverage or narrowly justified retention. No generic CI harness is proposed; any specific unresolved testability assessment belongs to task 3.2, and an unjustified removal blocks completion.

## Risks / Trade-offs

- Defaults can drift after upgrades → Run affected contract tests on dependency updates and review failures. Untested behavior changes remain an accepted risk. Use traceable evidence rather than immutable claims about floating hosted tools.
- Omission can preserve a value while changing shell failure handling or action behavior → Compare the complete invocation and retain settings needed by existing contracts. For example, explicit GitHub `shell: bash` and an unspecified shell [use different failure flags](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idstepsshell).
- Runtime evidence could require host or live-service mutation → Use existing disposable test environments and local resolution/dry runs. Do not execute bootstrap, deployments, bot approval, or publication against live resources.
- Explanation material can grow beyond its purpose → Apply the delta's behavioral-override boundary and locality rule, reusing existing locations. Do not keep a second ledger of deleted defaults.

## Migration Plan

Deliver ordinary repository edits through the existing review workflow. Land affected contract tests with their default cleanup. Other changes to command builders need focused behavioral checks only when static/default resolution cannot establish equivalence; no tests solely asserting that text was deleted. Rollback restores the removed settings and associated documentation through Git. No persistent data migration or production rollout is required.
