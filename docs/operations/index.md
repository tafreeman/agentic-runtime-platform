# Operations

Use these pages to configure, deploy, secure, and diagnose the FastAPI server.

## Before deployment

1. Read the [deployment guide](../deployment-guide.md).
2. Set production values from the
   [configuration reference](../configuration.md).
3. Apply the controls in
   [security hardening](security-hardening.md).
4. Review [known limitations](../KNOWN_LIMITATIONS.md).
5. Test the same artifact and environment settings that will run in
   production.

The development command is not a production process manager. Run the server
behind an appropriate proxy or platform service, keep secrets outside the
image, and use explicit health checks:

```text
GET /api/health
GET /api/health/ready
```

The first endpoint reports process health. Readiness also checks dependencies
needed to accept work.

## During operation

- Use structured logs and preserve the `run_id` for each workflow.
- Monitor failed steps, retries, model routing, provider errors, and latency.
- Keep workflow run storage on durable storage if run history matters.
- Confirm that each replica can reach the same required configuration and
  state.
- Treat model and evaluator output as untrusted data at system boundaries.

See [troubleshooting](troubleshooting.md) for startup, API, model, workflow,
RAG, and UI diagnostics.

## Related references

| Page | Use it for |
| --- | --- |
| [Runtime API contracts](../api-contracts-runtime.md) | Routes and request shapes |
| [Architecture](../ARCHITECTURE.md) | Component and execution boundaries |
| [No-LLM mode](../NO_LLM_MODE.md) | Deterministic and provider-free checks |
| [Migration guide](../MIGRATIONS.md) | Breaking changes between versions |
