# Security Policy

## Supported Versions

This project is under active development. Security fixes are applied to the default branch first.

| Version | Supported |
| --- | --- |
| `main` / latest | Yes |
| Older snapshots | Best effort |

## Reporting a Vulnerability

Please do not open public issues for suspected vulnerabilities.

Use one of these private paths:
- Create a GitHub Security Advisory draft (preferred), or
- Contact maintainers through the private support path in `SUPPORT.md`.

## What to Include

- Affected component and file path
- Reproduction steps or proof of concept
- Impact assessment (confidentiality, integrity, availability)
- Suggested mitigation (if available)

## Response Targets

- Initial acknowledgment: within 3 business days
- Triage decision: within 7 business days
- Fix timeline: based on severity and complexity

## Disclosure Policy

We follow coordinated disclosure:
- Keep details private until a fix is available
- Publish remediation details after patch release
- Credit reporters who want attribution

## Hardening Guidance for Contributors

- Never commit secrets, credentials, or private datasets.
- Keep API keys in environment variables.
- Resolve runtime secrets through `agentic_v2.models.secrets.get_secret()` / `get_first_secret()` instead of direct `os.environ` reads so the default provider chain, tests, and future secret backends behave consistently.
- HTTP API authentication is opt-in with `AGENTIC_API_KEY`; protected `/api/*` routes accept `Authorization: Bearer <key>` or `X-API-Key: <key>`.
- WebSocket clients must send credentials in headers, and browser origin checks still apply via `AGENTIC_CORS_ORIGINS`.
- Add tests for security-sensitive behavior changes
