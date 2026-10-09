# syntax=docker/dockerfile:1

# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

FROM python:3.14-slim@sha256:f85c5697265c178cc6887276c55fe16cf3d14ca35c3df6a5eab3b360534a55d2

LABEL org.opencontainers.image.source="https://github.com/vitormattos/git-signing-mcp" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        gnupg \
        openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

# The pip cache is a BuildKit cache mount and is not persisted in the image layer.
# hadolint ignore=DL3042
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install .

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin mcp
USER mcp

EXPOSE 8080

CMD ["python", "-m", "git_signing_mcp.server"]
