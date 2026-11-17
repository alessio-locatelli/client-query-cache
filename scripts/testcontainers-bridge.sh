# TESTCONTAINERS_RYUK_PRIVILEGED in the Distrobox and Toolbx branches: The default is inherited from ryuk.container.privileged in Testcontainers properties, otherwise false (https://github.com/testcontainers/testcontainers-python/blob/testcontainers-v4.15.0/src/testcontainers/core/config.py#L138-L142). We override it because Ryuk must clean disposable containers through rootless Podman's mounted socket.
if command -v distrobox-host-exec >/dev/null 2>&1 && [[ ! -e /run/.toolboxenv ]]; then
    uid="$(id -u)"
    export TESTCONTAINERS_RYUK_PRIVILEGED=true
    export DOCKER_HOST="unix:///run/host/run/user/${uid}/podman/podman.sock"
    export TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE="/run/user/${uid}/podman/podman.sock"
elif [[ -e /run/.toolboxenv ]]; then
    export TESTCONTAINERS_RYUK_PRIVILEGED=true
    export DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock"
fi
