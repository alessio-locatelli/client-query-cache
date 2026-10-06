if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
    return 0
fi

uid="$(id -u)"
# testcontainers 4.15.0: https://github.com/testcontainers/testcontainers-python/blob/testcontainers-v4.15.0/src/testcontainers/core/config.py
# The default is inherited from ryuk.container.privileged in Testcontainers properties, otherwise false. We override it because Ryuk must clean disposable containers through rootless Podman's mounted socket.
export TESTCONTAINERS_RYUK_PRIVILEGED=true
if command -v distrobox-host-exec >/dev/null 2>&1 && [[ ! -e /run/.toolboxenv ]]; then
    export DOCKER_HOST="unix:///run/host/run/user/${uid}/podman/podman.sock"
    export TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE="/run/user/${uid}/podman/podman.sock"
elif [[ -e /run/.toolboxenv ]]; then
    export DOCKER_HOST="unix:///run/user/${uid}/podman/podman.sock"
else
    printf 'Run this recipe inside a Toolbx or Distrobox container, or on GitHub Actions.\n' >&2
    exit 1
fi
