# Design

## Context

See `proposal.md` for the observed failure. [Fedora 45 was released on November 3, 2026](https://fedoramagazine.org/announcing-fedora-linux-45/); its [Node.js 26 packages](https://packages.fedoraproject.org/pkgs/nodejs26/nodejs26-bin/index.html) are available from Fedora repositories.

## Goals / Non-Goals

See the delta spec for the image contract. [Issue #312](https://github.com/alessio-locatelli/client-query-cache/issues/312) concerns a separate MongoDB/Ubuntu kernel incompatibility and remains outside this change.

## Decisions

### D1: Upgrade the base rather than change package sources

The user selected the Fedora upgrade. Use the registry's published multi-platform image digest and retain the existing DNF installation and `scripts/check_dev_container.sh` verification path.

Deferring the Node update would avoid an environment upgrade but leave PR #406 blocked. Installing Node from another source would retain the base but add another installation/update mechanism and depart from the existing DNF policy. Neither alternative needs further research or follow-up work.

### D2: Keep release selection in the container definition

Numbered Fedora releases outside the container definition duplicate a maintained image input without defining an additional compatibility guarantee. Contributor guidance can refer to that definition. The change-specific context above records why this upgrade was chosen.

The existing root Docker entry in `.github/dependabot.yml` already owns base-image updates on a monthly schedule. Dependabot's [file fetcher](https://github.com/dependabot/dependabot-core/blob/main/docker/lib/dependabot/docker/file_fetcher.rb) recognizes `Containerfile`, and its [shared updater](https://github.com/dependabot/dependabot-core/blob/main/docker/lib/dependabot/shared/shared_file_updater.rb) replaces both tags and digests. Add the missing base-image entry to the executable inventory; no competing Renovate manager or updater-policy change is needed. No further research or follow-up work is needed.

## Risks / Trade-offs

The base upgrade changes other Fedora packages too. The full container check must verify the installed toolchain as a non-root contributor, including Rust compilation and component installation. Refresh the contributor guide's rustup warning note against the actual build output. Library runtime code and test selection do not change, so matched runtime benchmarks are unnecessary.
