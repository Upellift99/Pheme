# Multi-arch (amd64 / arm64 / arm/v7) and slim. Some dependencies (pycryptodomex,
# pulled in by huawei-lte-api) ship no prebuilt wheel for arm/v7, so they must be
# compiled. We do that in a throwaway builder stage that carries the toolchain,
# then install the resulting wheels into a clean slim image with no compiler.

FROM python:3.14-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
# Build wheels for the project and all its dependencies into /wheels.
RUN pip wheel --no-cache-dir --wheel-dir /wheels .


FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STATE_DB=/data/state.db

WORKDIR /app

# Install purely from the prebuilt wheels — no network, no compiler needed.
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels pheme \
    && rm -rf /wheels

# Run as an unprivileged user and own the state volume.
RUN useradd --create-home --uid 1000 pheme \
    && mkdir -p /data \
    && chown -R pheme:pheme /data
USER pheme

VOLUME ["/data"]

HEALTHCHECK --interval=60s --timeout=15s --start-period=20s --retries=3 \
    CMD pheme-healthcheck || exit 1

ENTRYPOINT ["pheme"]
