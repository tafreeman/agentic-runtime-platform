# Security policy

## Supported code

Security fixes are applied to the repository's default branch. Older commits
and unmaintained snapshots do not have a guaranteed support window.

## Report a vulnerability

Do not open a public issue for a suspected vulnerability.

Use a private
[GitHub Security Advisory](https://github.com/tafreeman/agentic-runtime-platform/security/advisories/new).
If that path is unavailable, contact a maintainer privately and ask for a
secure reporting channel. Do not send exploit details, credentials, or private
data through a public issue.

Include:

- the affected component and version or commit;
- the required configuration and deployment assumptions;
- minimal reproduction steps or a proof of concept;
- the expected and observed behavior;
- the confidentiality, integrity, or availability impact; and
- a suggested mitigation, if known.

Maintainers will confirm receipt, assess scope and severity, coordinate a fix,
and agree on disclosure timing with the reporter. Response time depends on
maintainer availability and issue complexity; this project does not publish a
support SLA.

## Contributor requirements

- Never commit credentials, LAF tokens, private keys, or private datasets.
- Use the runtime secret-provider layer instead of adding direct environment
  reads for provider credentials.
- Add negative tests for authentication, authorization, path, URL, command,
  output-handling, and resource-limit changes.
- Keep file and Git tools inside a configured sandbox.
- Keep shell access disabled unless a reviewed workflow needs an explicit
  executable allowlist.
- Treat model, retrieval, tool, and MCP output as untrusted input.
- Document settings that weaken a fail-closed control.

See:

- [Security hardening](../docs/operations/security-hardening.md)
- [OWASP LLM threat review](../docs/OWASP_LLM_THREAT_MODEL.md)
- [Supply-chain security](../docs/SUPPLY_CHAIN.md)
- [Known limitations](../docs/KNOWN_LIMITATIONS.md)

These guides describe source controls and deployment responsibilities. They
are not a compliance certification or penetration-test result.
