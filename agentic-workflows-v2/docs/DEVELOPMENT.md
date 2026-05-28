# Development Guide

## Local Environment

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev,server,langchain]"
```

UI dependencies:

```bash
cd ui
npm install
cd ..
```

## Day-to-Day Commands

### CLI and workflow checks

```bash
agentic list workflows
agentic validate code_review
agentic run code_review --dry-run
```

### Backend server

```bash
python -m uvicorn agentic_v2.server.app:app --host 127.0.0.1 --port 8010
```

### UI dev mode

```bash
# backend first (port 8000)
python -m uvicorn agentic_v2.server.app:app --host 127.0.0.1 --port 8000

# then frontend
cd ui
npm run dev
```

### Combined helper script

```bash
bash dev.sh
```

## Testing and Quality

```bash
pre-commit run --all-files
python -m pytest tests -v
python -m pytest --cov=agentic_v2 --cov-report=term-missing --cov-report=xml
python scripts/check_docs_refs.py
```

UI tests:

```bash
cd ui
npm test
npm run test:coverage
```

## Logs and Run Artifacts

- Runtime logs: `.run-logs/`
- Run outputs/events: `runs/` (generated and typically not committed)
- Fixture samples for docs/tests: `fixtures/`

## Environment Variables Most Used In Development

- `AGENTIC_API_KEY`
- `AGENTIC_CORS_ORIGINS`
- `AGENTIC_MODEL_TIER_1`, `AGENTIC_MODEL_TIER_2`, `AGENTIC_MODEL_TIER_3`
- `AGENTIC_MEMORY_PATH`
- `AGENTIC_TRACING`, `AGENTIC_TRACE_SENSITIVE`
