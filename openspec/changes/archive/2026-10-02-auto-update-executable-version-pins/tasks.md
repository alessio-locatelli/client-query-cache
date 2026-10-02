# Tasks

## 1. Official integration and ownership

- [x] 1.1 Configure the official hosted Renovate app, built-in `github-actions` and `pyenv` managers, and regex managers only for unsupported selections. Disable non-`uses-with` Actions updates to preserve Dependabot ownership. Record the official runner comparison in design.md.
- [x] 1.2 Preserve monthly reviewable proposals, release tracks, and seven-day age checks where timestamps exist. Ensure sources without timestamps are not blocked indefinitely.
- [x] 1.3 Add the official strict repository config-validation hook under Dependabot ownership and document stable extraction/lookup commands and the ownership inventory. Keep bot installation an administrator operation.

## 2. Canonical toolchain and coupled inputs

- [x] 2.1 Derive CI Prek installation and cache identity from one selection, grouped with the container pin.
- [x] 2.2 Centralize CI uv in the composite action. Let uv consume `.python-version`, hash that file for cache identity, and use it for container Python installation. Remove duplicate workflow versions and redundant Python overrides.
- [x] 2.3 Install Fedora DNF tools by package name, preserving Fedora 44 and Node.js 24 tracks and non-DNF pins. Document variable RPM revisions and the low expected development-tool risk; define the container contract accordingly.
- [x] 2.4 Use the official release-attachment datasource and coupled Taplo ARG/URL/checksum replacement. Verify matching tool versions and rejection of invalid downloads through the build checker.

## 3. Consumer validation

- [x] 3.1 Select package, container, and isolated benchmark checks from their actual inputs. Add parametrized scope cases for managed inputs, unrelated workflows, report code, and documentation.
- [x] 3.2 Build/check container tools and bound isolated replica-set startup after applicable quality checks. Preserve stable check names and document ruleset prerequisites.
- [x] 3.3 Run both performance-guard revisions with the proposed interpreter, retain mismatch/base-failure handling, and record actual interpreter versions.

## 4. Completion

- [x] 4.1 Compare official extraction with ownership and exclusions, inspect lookup diagnostics, and validate scope behavior. Keep diagnostic output and validation history out of contributor documentation.
- [x] 4.2 Review the amended original change, sync its specs, archive, and commit after required checks pass.
