# Contributing

Develop inside the pinned Toolbx or Distrobox image, or an equivalent environment with the declared
tools on `PATH`.

## Prerequisites

- [Rootless Podman](https://podman.io/docs/installation) and a systemd user session
- [Toolbx](https://containertoolbx.org/install/) with `flatpak-spawn` and a working Flatpak
  portal/session helper, or [Distrobox](https://distrobox.it/#installation)

## Environment

From the host, build the image and create a Toolbx container:

```console
podman build --tag localhost/mongodb-client-cache-dev:0.1.0 --file Containerfile .
podman container exists mongodb-client-cache-dev || toolbox create --image localhost/mongodb-client-cache-dev:0.1.0 mongodb-client-cache-dev
```

For Distrobox, use:

```console
podman container exists mongodb-client-cache-dev || distrobox create --image localhost/mongodb-client-cache-dev:0.1.0 --name mongodb-client-cache-dev
```

Inside the container, open the checkout and run:

```console
just setup
```

## Validate changes

Inside Toolbx or Distrobox, enable the host Podman socket before the full test suite:

```console
just enable-podman-socket
just coverage
```

`just coverage` runs the current test suite and reports coverage. `just test` is the container-free
unit-test command. To discover focused recipes, run:

```console
just --list | grep -E 'test|coverage'
```

Use pytest directly for its selection options. Run `just lint` and `just format` for repository
quality checks, and run `just ci-lint` after changing GitHub Actions.

Run host Podman commands from the contributor container with `just podman -- <arguments>`.
