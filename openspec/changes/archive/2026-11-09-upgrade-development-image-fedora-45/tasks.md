# Tasks

## 1. Contributor image

- [x] 1.1 Apply design D1 in `Containerfile` and align `CONTRIBUTING.md` and `docs/development/executable-version-updates.md`; verify with `bash scripts/check_dev_container.sh flatpak-spawn --host podman` and inspect the build log for warnings.
- [x] 1.2 Apply design D2 to the delta and main development-environment spec; compare their requirement blocks and confirm the diff preserves every obligation except the numbered Fedora selection.
- [x] 1.3 Remove the remaining numbered Fedora selections from contributor guidance and the Containerfile comment, and add the base image's updater ownership to the executable inventory per D2; inspect the remaining matches to distinguish maintained selections from historical measurement evidence.

## 2. Code Quality

- [x] 2.1 Check edited test files against the Writing Tests guidelines: no test files are changed.
- [x] 2.2 Check the Claude-only prose restriction: inapplicable, implemented by Codex.
