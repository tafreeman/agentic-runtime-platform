# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS python-base

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
    && pip install --no-cache-dir -e . \
    && pip install --no-cache-dir -e "./agentic-workflows-v2[dev,server,tracing]" \
    && pip install --no-cache-dir -e "./agentic-v2-eval[dev]"

WORKDIR /workspace/agentic-workflows-v2
EXPOSE 8010

CMD ["python", "-m", "uvicorn", "agentic_v2.server.app:app", "--host", "0.0.0.0", "--port", "8010", "--reload"]


FROM python-base AS devcontainer

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g npm@latest \
    && rm -rf /var/lib/apt/lists/*

COPY . /workspace

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -e . \
    && pip install --no-cache-dir -e "./agentic-workflows-v2[dev,server,tracing]" \
    && pip install --no-cache-dir -e "./agentic-v2-eval[dev]" \
    && npm --prefix /workspace/agentic-workflows-v2/ui install

CMD ["sleep", "infinity"]
