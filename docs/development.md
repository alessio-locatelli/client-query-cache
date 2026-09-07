# Development environment

The project provides a pinned development image for Toolbx and Distrobox. Run the setup and quality commands inside that container, or in an equivalent environment with the declared tools already on `PATH`.

## Host prerequisites

- [Rootless Podman](https://podman.io/docs/installation)
- A [systemd user session](https://www.freedesktop.org/software/systemd/man/latest/systemd.user.html)
- [Toolbx](https://containertoolbx.org/install/) with [`flatpak-spawn`](https://flatpak.org/setup/) and a working Flatpak portal/session helper, or [Distrobox](https://distrobox.it/#installation)

## Create the environment

From the host shell, build the image and create one supported container:

```console
podman build --tag localhost/mongodb-client-cache-dev:0.1.0 --file Containerfile .
podman container exists mongodb-client-cache-dev || toolbox create --image localhost/mongodb-client-cache-dev:0.1.0 mongodb-client-cache-dev
```

Use `podman container exists mongodb-client-cache-dev || distrobox create --image localhost/mongodb-client-cache-dev:0.1.0 --name mongodb-client-cache-dev` instead for Distrobox. The matching `just build-dev-image`, `just create-toolbox`, and `just create-distrobox` recipes are optional conveniences when `just` is already available on the host.

Enter the resulting `mongodb-client-cache-dev` container, open the mounted checkout, and initialize the repository:

```console
just setup
```

## Quality and tests

```console
just lint
just format
just test
just test-integration
just test-e2e
just coverage
```

`just test` is the container-free unit tier. The integration, end-to-end, and coverage recipes require the host Podman API socket. Run `just enable-podman-socket` once inside the contributor container before using them.

Run `just ci-lint` after changing CI configuration. Run host Podman commands from the contributor container with `just podman -- <arguments>`.

## Continuous integration

Every pull request runs three GitHub Actions jobs in sequence, each gating the next so a cheap failure stops before an expensive one starts:

1. **Quality, packaging, and isolated install** — the same checks as `just lint`, plus building the source and wheel distributions and importing the wheel in an isolated environment.
2. **Unit tests** — the same tests as `just test`.
3. **Docker-backed integration, end-to-end, and coverage** — the same tests as `just coverage` and `just test-e2e`, run against a disposable MongoDB replica set. Coverage and failure diagnostics are uploaded as short-lived build artifacts.

A pull request limited to documentation or OpenSpec planning files does not trigger CI.
