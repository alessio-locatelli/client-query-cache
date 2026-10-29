FROM registry.fedoraproject.org/fedora-toolbox:44@sha256:b3a0088e7a72ea2c7cb496c674a3e11201960814d4303e19ab2746afaca5fad5

# renovate: datasource=pypi depName=prek versioning=pep440
ARG PREK_TOOL_VERSION=0.5.4
# renovate: datasource=pypi depName=zizmor versioning=pep440
ARG ZIZMOR_TOOL_VERSION=1.30.1

# renovate-taplo: datasource=github-release-attachments depName=tamasfe/taplo
ARG TAPLO_TOOL_VERSION=0.10.0

ADD --checksum=sha256:8fe196b894ccf9072f98d4e1013a180306e17d244830b03986ee5e8eabeb6156 https://github.com/tamasfe/taplo/releases/download/0.10.0/taplo-linux-x86_64.gz /tmp/taplo.gz

# Dockerfile ENV inheritance: https://docs.docker.com/reference/dockerfile/#env
# PATH: The default is inherited from the pinned Fedora base image. We override it because installed project tools in /usr/local/bin and the rustup proxies must precede system binaries.
# rustup 1.29 CARGO_HOME and RUSTUP_HOME: https://rust-lang.github.io/rustup/installation/index.html#choosing-where-to-install
# The defaults are ~/.cargo and ~/.rustup. We override them because the contributor's host account must use and update the image's Rust toolchain and Cargo caches.
ENV PATH=/usr/local/bin:/opt/cargo/bin:${PATH} \
    CARGO_HOME=/opt/cargo \
    RUSTUP_HOME=/opt/rustup \
    UV_PYTHON_BIN_DIR=/usr/local/bin \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_TOOL_BIN_DIR=/usr/local/bin \
    UV_TOOL_DIR=/opt/uv-tools

COPY .python-version /tmp/python-version
COPY .node-version /tmp/node-version
COPY rust-toolchain.toml /tmp/rust-toolchain-selection.toml

# Fedora packages follow the Fedora 44 repositories; see CONTRIBUTING.md for the rationale.
# DNF5 --assumeyes: https://dnf5.readthedocs.io/en/latest/dnf5.8.html
# The default is inherited from DNF configuration (assumeyes=false unless configured). We override it because container builds cannot answer interactive package prompts.
# rustup-init 1.29 --help: -y: The default prompts for confirmation. We override it because container builds cannot answer prompts.
# --profile: The default is default. We override it because the image provides the source-build toolchain and just setup-rust adds development components.
# --default-toolchain: The default is stable. We override it because Rust tools outside the checkout must use the selected release.
RUN NODE_TOOL_VERSION="$(cat /tmp/node-version)" \
    && NODE_MAJOR="${NODE_TOOL_VERSION%%.*}" \
    && dnf install --assumeyes \
        bash \
        gcc \
        gh \
        just \
        "nodejs${NODE_MAJOR}" \
        "nodejs${NODE_MAJOR}-npm" \
        rustup \
        uv \
    && dnf clean all \
    && rustup-init -y --profile minimal \
        --default-toolchain "$(python3 -c 'import sys, tomllib; print(tomllib.load(sys.stdin.buffer)["toolchain"]["channel"])' < /tmp/rust-toolchain-selection.toml)" \
    && PYTHON_TOOL_VERSION="$(cat /tmp/python-version)" \
    && uv python install "${PYTHON_TOOL_VERSION}" \
    && chmod -R a+w "${CARGO_HOME}" "${RUSTUP_HOME}" "${UV_PYTHON_INSTALL_DIR}" \
    && uv tool install --python "${PYTHON_TOOL_VERSION}" "prek==${PREK_TOOL_VERSION}" \
    && uv tool install --python "${PYTHON_TOOL_VERSION}" "zizmor==${ZIZMOR_TOOL_VERSION}" \
    && gzip --decompress --stdout /tmp/taplo.gz > /usr/local/bin/taplo \
    && chmod 0755 /usr/local/bin/taplo \
    && test "$(taplo --version)" = "taplo ${TAPLO_TOOL_VERSION}"

LABEL com.github.containers.toolbox="true" \
      org.opencontainers.image.title="client-query-cache development environment"
