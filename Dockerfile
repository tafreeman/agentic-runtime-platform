# syntax=docker/dockerfile:1.7

FROM python:3.13-slim AS python-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl git \
    && rm -rf /var/lib/apt/lists/*


FROM python-base AS backend-dev

COPY . /workspace

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -e . -c ci-constraints.txt \
    && pip install --no-cache-dir -e "./agentic-workflows-v2[dev,server,tracing]" -c ci-constraints.txt \
    && pip install --no-cache-dir -e "./agentic-v2-eval[dev]" -c ci-constraints.txt

# Run as non-root user (S6471)
RUN groupadd --system appgroup \
    && useradd --system --gid appgroup --no-create-home appuser \
    && chown -R appuser:appgroup /workspace
USER appuser

WORKDIR /workspace/agentic-workflows-v2
EXPOSE 8010

CMD ["python", "-m", "uvicorn", "agentic_v2.server.app:app", "--host", "0.0.0.0", "--port", "8010", "--reload"]


FROM python-base AS production

COPY . /workspace

# Install only runtime extras — no dev/test tooling (pytest, mypy, black, etc.)
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -e . -c ci-constraints.txt \
    && pip install --no-cache-dir -e "./agentic-workflows-v2[server,tracing]" -c ci-constraints.txt

# Run as non-root user (S6471) — mirrors the dev stage setup
RUN groupadd --system appgroup \
    && useradd --system --gid appgroup --no-create-home appuser \
    && chown -R appuser:appgroup /workspace
USER appuser

WORKDIR /workspace/agentic-workflows-v2
EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8010/api/health || exit 1

CMD ["uvicorn", "agentic_v2.server.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8010"]


FROM python-base AS devcontainer

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g npm@latest \
    && rm -rf /var/lib/apt/lists/*

COPY . /workspace

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -e . -c ci-constraints.txt \
    && pip install --no-cache-dir -e "./agentic-workflows-v2[dev,server,tracing]" -c ci-constraints.txt \
    && pip install --no-cache-dir -e "./agentic-v2-eval[dev]" -c ci-constraints.txt \
    && npm --prefix /workspace/agentic-workflows-v2/ui install \
    && groupadd --system appgroup \
    && useradd --system --gid appgroup --no-create-home appuser \
    && chown -R appuser:appgroup /workspace
# Run as non-root user (S6471)
USER appuser

CMD ["sleep", "infinity"]
