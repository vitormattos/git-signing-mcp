FROM python:3.13-slim@sha256:59d365aafe9c497e90af2caf4affe3e57f677328b251945b0327807887ed3772

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

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

RUN pip install .

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin mcp
USER mcp

EXPOSE 8080

CMD ["python", "-m", "git_signing_mcp.server"]
