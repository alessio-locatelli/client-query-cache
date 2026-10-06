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

**Goals:** Use the inventory below as the audit boundary and keep explanations maintainable beside their owning configuration or in a single maintainer reference.

**Non-Goals:** Change public Python defaults, redesign pipelines, alter live settings, upgrade dependencies to make cleanup possible, or introduce a generic default-detection checker.

## Decisions

### 1. Audit all owned tool surfaces using a bounded inventory

| Group                                  | Owned surfaces                                                                                                                                                                                                                                                                              |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A: Documentation and update automation | `zensical.toml`, `stable-docs.toml`, `lychee.toml`, `context7.json`, `renovate.json5`, `.github/dependabot.yml`                                                                                                                                                                             |
| B: Quality, packaging, and testing     | `pyproject.toml`, `ruff.toml`, `mypy.ini`, `pytest.ini`, `tox.ini`, `.coveragerc`, `.pre-commit-config.yaml`, `.gitlint`, `.taplo.toml`, `_typos.toml`, `.markdownlint-cli2.jsonc`, `.github/actionlint.yaml`, `package.json`, `.gitattributes`, `.gitignore`, `.prettierignore`            |
| C: Automation and runtime bootstrap    | `justfile`, `.github/workflows/*.yml`, `.github/actions/setup-toolchain/action.yml`, `Containerfile`, `docker-compose.yaml`, `scripts/*.py`, `scripts/*.sh`, and command/configuration builders used for disposable MongoDB in `tests/conftest.py` and `benchmarks/stream_cost/topology.py` |
| D: Other owned occurrences             | Additional tracked configuration or automation discovered by the scoped scan, including executable command examples in contributor/tooling documentation and flags in other benchmark orchestration modules                                                                                 |

Use `git ls-files` to enumerate tracked candidates, plain-text search for options/flags, and structural navigation for command builders. Classify optional behavioral settings and flags, including environment-controlled options, rather than requiring explanations for schema structure or program data. Required project identity, version/checksum metadata, regex patterns, action identifiers, and operands are not overrides merely because they appear in configuration. Optional project-specific settings such as navigation, paths, or an enabled plugin still need explanations when they replace an unset/default value. Definitions of application or Python function defaults are outside this tool-invocation audit.

Exclude submodule contents, symlinks, generated output, lockfile contents as editing targets, historical reports, archived changes, agent skill bundles, and illustrative test fixtures. Lockfiles remain evidence for selected tool versions. Sensitive files, including `.env`, `.env.example`, and `.secrets.baseline`, are not read or edited by this audit; credential references in ordinary workflows remain in scope.

The alternative of restricting the audit to the named examples costs less initially but misses equivalent problems elsewhere. Its coverage limitation is already established; no prototype or further research is needed. A scan of every Python default would greatly expand scope into application design without improving tool configuration clarity; no further research is needed for rejecting it.

### 2. Compare behavior with only the candidate occurrence omitted

Establish the selected version from lockfiles, action SHAs, hook revisions, and tool pins. Read official version-matched docs/help/schema/source. For hosted tools or Fedora-provided tools without an exact runtime pin, record the documented/tested version and relevant execution context rather than claim a frozen default. Resolve relevant preset chains, wrapper exports, hook defaults, command precedence, and inherited Git settings before classifying an occurrence.

Use a temporary working audit ledger with file/key or command, supplied value, effective value when omitted, authoritative evidence, context, and removal or rationale destination. Keep it untracked; a permanent duplicate inventory would recreate configuration noise. An unresolved comparison blocks completion, as specified in the delta.

Comparing only built-in default tables is faster but fails the Renovate and Git examples above. No further research is needed to reject that approach. Building a universal checker would require tool-specific semantic resolution and maintain a second configuration model. Existing official validators remain appropriate for syntax and supported options, with review enforcing the rationale policy; no prototype is needed.

### 3. Give each explanation one maintained home

Use concise inline comments when the format supports them and the override is local. Use an existing relevant OpenSpec requirement only if it contains the required explanation and identifies the actual option. For JSON, long explanations, and shared command flags, create `docs/development/configuration-overrides.md` with tool/key or command identifiers, applicable defaults/context, source links and versions, and the required rationale sentence. Group occurrences only under the delta's shared-explanation rule. Do not repeat an inline explanation in that document.

Link the maintainer reference from `CONTRIBUTING.md`. Add a short `AGENTS.md` pointer to the canonical development-environment requirement so future edits discover the rule without duplicating it. Public usage guides require edits only where an executable example itself contains a redundant flag; keep override mechanics in maintainer material.

Documenting everything inline has excellent locality but cannot serve strict JSON and becomes repetitive for shared flags. Documenting everything in specifications is allowed but scatters operational explanations across behavioral contracts. Neither has unresolved technical unknowns, and neither needs further research. The mixed placement provides one explanation per override while preserving discoverability.

## Risks / Trade-offs

- Defaults can drift after upgrades → Recheck affected entries under the delta's maintenance requirement; use traceable evidence rather than immutable claims about floating hosted tools.
- Omission can preserve a value while changing shell failure handling or action behavior → Compare the complete invocation and retain settings needed by existing contracts. For example, explicit GitHub `shell: bash` and an unspecified shell [use different failure flags](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idstepsshell).
- Runtime evidence could require host or live-service mutation → Use existing disposable test environments and local resolution/dry runs. Do not execute bootstrap, deployments, bot approval, or publication against live resources.
- A comprehensive explanation reference can be lengthy → Keep only retained overrides, use precise grouped entries, and remove stale material. Do not keep a second ledger of deleted defaults.

## Migration Plan

Deliver ordinary repository edits through the existing review workflow. Changes to command builders need focused behavioral checks only when static/default resolution cannot establish equivalence; no tests solely asserting that text was deleted. Rollback restores the removed settings and associated documentation through Git. No persistent data migration or production rollout is required.
