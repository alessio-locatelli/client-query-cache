FROM registry.fedoraproject.org/fedora-toolbox:44@sha256:b3a0088e7a72ea2c7cb496c674a3e11201960814d4303e19ab2746afaca5fad5

# renovate: datasource=pypi depName=prek versioning=pep440
ARG PREK_TOOL_VERSION=0.5.2
# renovate: datasource=pypi depName=zizmor versioning=pep440
ARG ZIZMOR_TOOL_VERSION=1.30.0

# renovate: datasource=github-release-attachments depName=tamasfe/taplo
ARG TAPLO_TOOL_VERSION=0.10.0

ADD --checksum=sha256:8fe196b894ccf9072f98d4e1013a180306e17d244830b03986ee5e8eabeb6156 https://github.com/tamasfe/taplo/releases/download/0.10.0/taplo-linux-x86_64.gz /tmp/taplo.gz

ENV PATH=/usr/local/bin:${PATH} \
    UV_PYTHON_BIN_DIR=/usr/local/bin \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_TOOL_BIN_DIR=/usr/local/bin \
    UV_TOOL_DIR=/opt/uv-tools

COPY .python-version /tmp/python-version

# Fedora packages follow the Fedora 44 repositories; see CONTRIBUTING.md for the rationale.
RUN dnf install --assumeyes \
        bash \
        just \
        nodejs24 \
        nodejs24-npm \
        uv \
    && dnf clean all \
    && PYTHON_TOOL_VERSION="$(cat /tmp/python-version)" \
    && uv python install "${PYTHON_TOOL_VERSION}" \
    && uv tool install --python "${PYTHON_TOOL_VERSION}" "prek==${PREK_TOOL_VERSION}" \
    && uv tool install --python "${PYTHON_TOOL_VERSION}" "zizmor==${ZIZMOR_TOOL_VERSION}" \
    && gzip --decompress --stdout /tmp/taplo.gz > /usr/local/bin/taplo \
    && chmod 0755 /usr/local/bin/taplo \
    && test "$(taplo --version)" = "taplo ${TAPLO_TOOL_VERSION}"

LABEL com.github.containers.toolbox="true" \
      org.opencontainers.image.title="client-query-cache development environment"
