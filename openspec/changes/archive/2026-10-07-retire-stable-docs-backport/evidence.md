# Delivery evidence

The automatic combined build selected published `v0.3.0` and rendered stable, development, and root redirects. An explicit local tag also built successfully with `GH_REPO` pointing to an unavailable repository, confirming that reproduction skips discovery and fetching. A depth-one disposable clone completed automatic assembly with the delivered recipe and assembler.

Native recipe probes in disposable checkouts stopped on an unavailable release endpoint (exit 1) and inaccessible origin (exit 128), before creating site output. The existing contributor-image smoke check verified the Fedora-provided GitHub CLI. The full test and strict-no-cover gate reached 100% coverage.

One local automatic build with warmed dependencies took 7.10 seconds; GNU time reported maximum RSS of 64,184 KiB, and `du` reported a 4.0 MiB site. This is one tooling-workload measurement, not a comparative performance claim. Reproduce with:

```console
/usr/bin/time -f '%e seconds; %M KiB peak RSS' just docs-build-editions
du -sh site
just tests_and_coverage
bash scripts/check_dev_container.sh flatpak-spawn --host podman
```

Raw logs and measurements remain untracked. The unrelated requirement-length notices have an assigned open owner in [issue #185](https://github.com/alessio-locatelli/client-query-cache/issues/185).
