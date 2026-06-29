# Slim, non-root, multi-arch image. The base python:3.11-slim is published for
# amd64, arm64 and arm/v7, and all dependencies are pure Python, so the same
# Dockerfile builds for a Raspberry Pi without any cross-compilation toolchain.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STATE_DB=/data/state.db

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Run as an unprivileged user and own the state volume.
RUN useradd --create-home --uid 1000 pheme \
    && mkdir -p /data \
    && chown -R pheme:pheme /data
USER pheme

VOLUME ["/data"]

HEALTHCHECK --interval=60s --timeout=15s --start-period=20s --retries=3 \
    CMD pheme-healthcheck || exit 1

ENTRYPOINT ["pheme"]
