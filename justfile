set shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

venv_python := ".venv/Scripts/python.exe"
backend_port := "8010"
frontend_port := "5173"

default:
    @just --list

_require-venv:
    if (-not (Test-Path "{{venv_python}}")) { throw "Virtual environment not found at {{venv_python}}. Run: just setup" }

venv:
    if (-not (Test-Path "{{venv_python}}")) { python -m venv .venv }

setup: venv
    & "{{venv_python}}" -m pip install --upgrade pip
    & "{{venv_python}}" -m pip install -e .
    & "{{venv_python}}" -m pip install -e "./agentic-workflows-v2[dev,server,langchain,tracing]"
    & "{{venv_python}}" -m pip install -e "./agentic-v2-eval[dev]"
    npm --prefix agentic-workflows-v2/ui install

test: _require-venv
    & "{{venv_python}}" -m pytest agentic-workflows-v2/tests -v
    & "{{venv_python}}" -m pytest agentic-v2-eval/tests -v
    & "{{venv_python}}" -m pytest tests/e2e -v
    npm --prefix agentic-workflows-v2/ui test

docs: _require-venv
    & "{{venv_python}}" agentic-workflows-v2/scripts/check_docs_refs.py

dev:
    & "./agentic-workflows-v2/scripts/start-dev.ps1" -BackendPort {{backend_port}} -FrontendPort {{frontend_port}} -ApiProxyTarget "http://127.0.0.1:{{backend_port}}"

dev-reload:
    & "./agentic-workflows-v2/scripts/start-dev.ps1" -Reload -BackendPort {{backend_port}} -FrontendPort {{frontend_port}} -ApiProxyTarget "http://127.0.0.1:{{backend_port}}"

dev-stop:
    & "./agentic-workflows-v2/scripts/stop-dev.ps1"

dev-status:
    & "./agentic-workflows-v2/scripts/status-dev.ps1"

compose-up:
    docker compose up --build backend frontend otel-collector jaeger

compose-down:
    docker compose down --remove-orphans

compose-logs service="backend":
    docker compose logs -f {{service}}
