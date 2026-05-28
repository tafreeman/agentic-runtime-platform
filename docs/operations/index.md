# Operations

Operator-facing documentation for deploying and running the platform in production.
These pages assume the server is deployed from the `agentic-workflows-v2/` package and
accessible via uvicorn or a container.

---

## Pages in this section

| Page | Description |
|------|-------------|
| [Security Hardening](security-hardening.md) | Security knobs, rate limiting, auth throttling, filesystem sandboxing, sanitization, and CORS |
| [Troubleshooting](troubleshooting.md) | Common failure modes, log patterns, and diagnostic recipes |
| [Deployment Guide](../deployment-guide.md) | CI/CD pipeline, Docker, environment setup, and observability |

---

## Companion references

| Reference | Description |
|-----------|-------------|
| [Configuration Reference](../configuration.md) | Every environment variable, its default, and accepted values |
| [Known Limitations](../KNOWN_LIMITATIONS.md) | Current rough edges — in-process caveats, multi-replica behavior, and deferred Sprint 2 work |
| [Architecture](../ARCHITECTURE.md) | Runtime engine internals — DAG executor, adapter registry, RAG pipeline |

---

## Where to start

If you are hardening a new production deployment, begin with [Security Hardening](security-hardening.md)
and work through the **Reference deployment posture** section at the bottom of that page.
The copy-pasteable `.env` block there represents the minimum recommended configuration
for an internet-exposed instance.

If the server is not starting, see [Troubleshooting](troubleshooting.md) for startup
failure patterns. The most common cause is a missing LangChain extras install; the
[Security Hardening](security-hardening.md#5-adapter-eager-validation) page explains
how to bypass this with `AGENTIC_DEFAULT_ADAPTER=native`.

!!! note "mkdocs.yml nav"
    Navigation wiring for this section is maintained separately in `mkdocs.yml`.
    If you add a new page here, update the nav block there.
