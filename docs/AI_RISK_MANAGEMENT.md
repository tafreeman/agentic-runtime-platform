# AI Risk Management Framework Alignment

**Document type:** Engineering alignment artifact  
**Date:** 2026-05-11  
**Scope:** `tafreeman/agentic-runtime-platform` — multi-agent workflow orchestration platform (v0.3.0)  
**Reference framework:** NIST AI Risk Management Framework 1.0 (January 2023)  
**Status:** Living document — updated with each major release

> **Disclaimer:** This document is an engineering alignment artifact, not a formal NIST AI RMF assessment or Authorization to Operate (ATO) package. It maps existing engineering governance practices to AI RMF sub-categories to demonstrate organizational risk awareness and to identify gaps requiring future investment. It does not constitute a formal risk determination, ATO boundary document, or compliance certification.

---

## Introduction

The NIST AI Risk Management Framework (AI RMF 1.0) provides a voluntary, risk-based structure for managing trustworthiness, accountability, and transparency in AI systems. It is increasingly referenced in federal AI governance policy — including OMB Memorandum M-24-10 and the 2024 AI Executive Order implementation guidance — and is the baseline expectations document for AI system delivery in most federal agency contexts.

This document demonstrates how the engineering governance artifacts already present in this repository correspond to the four AI RMF functions: GOVERN, MAP, MEASURE, and MANAGE. It is written for a technical audience — solutions architects, delivery leads, and technical reviewers evaluating this platform for enterprise or federal contexts. It is not written for compliance personnel; those audiences should treat this as background context rather than a substitute for a formal ATO package.

The scope is bounded to this platform as a software artifact. This platform provides multi-agent workflow orchestration infrastructure — a runtime that executes YAML-defined agent graphs against external LLM providers. It does not make autonomous decisions in high-stakes domains. It is intended to augment human decision-making, not replace it. The platform is not designed for, and should not be deployed in, contexts requiring autonomous high-stakes decisions (medical diagnosis, criminal justice, weapons systems selection) without substantial additional human oversight controls beyond what this repository provides.

---

## GOVERN Function

The GOVERN function establishes the organizational policies, culture, and accountability structures that make risk management possible across the AI lifecycle. Controls in this function answer: who is responsible, what policies govern behavior, and how are decisions made and documented?

| Sub-Category | Description | Artifact / Control | Implementation Status |
|---|---|---|---|
| **GOVERN-1.1** | Policies, processes, procedures, and practices for AI risk management are documented and in place | `CONTRIBUTING.md` — branching policy, PR gates, commit format, code review requirements; `docs/CODING_STANDARDS.md` — Black, isort, ruff, mypy --strict, PEP 8 naming, 80% coverage mandate; `docs/adr/ADR-INDEX.md` — 13 decision records governing architecture choices; pre-commit hooks enforcing detect-secrets, docformatter, pydocstyle | Implemented. Policies enforced by CI gates (ci.yml, eval-package-ci.yml, nightly.yml, dependency-review.yml). Attribution is disabled by explicit policy to prevent credential leakage. |
| **GOVERN-1.2** | Accountability for AI risk management is defined and assigned | `CONTRIBUTING.md` §6 (ADR authorship), `CONTRIBUTING.md` §5 (commit attribution), `agentic-workflows-v2/SECURITY.md` (maintainer contact paths, 3-day acknowledgment SLA, 7-day triage SLA); PR review required before any merge | Partial. Single-maintainer repository — named roles (author, reviewer, security contact) exist but are not backed by an organizational RACI. Adequate for portfolio/prototype context; would require formal RACI expansion for multi-team delivery. |
| **GOVERN-1.7** | AI risk management is integrated with broader enterprise risk management | `docs/adr/ADR-002` (circuit breaker hardening — documents provider risk tolerance, cascade failure mitigations, per-provider bulkhead isolation); `docs/KNOWN_LIMITATIONS.md` — honest accounting of 10+ known limitations with status, workarounds, and upstream fix tracking; `ROADMAP.md` — risk items surfaced as Sprint B debt, not buried | Partial. Limitations are documented rather than formally triaged against an enterprise risk register. No formal risk acceptance authority is named. |
| **GOVERN-2.1** | Organizational teams understand their roles in AI risk management | `CONTRIBUTING.md` §3 — developer workflow explicitly includes security boundary review before ADR authorship; `docs/adr/ADR-007` — stop policy and classification matrix; `CONTRIBUTING.md` §6 — when to write an ADR (includes "change a security boundary, tool allowlist, secret source, auth model") | Partial. Role clarity is embedded in contribution guidance, not a standalone responsibility matrix. Sufficient for a portfolio context. |
| **GOVERN-4.1** | Organizational teams are trained to understand and manage AI risks | `docs/ONBOARDING.md`, `docs/WORKFLOW_AUTHORING.md`, and `docs/OWASP_LLM_THREAT_MODEL.md` provide written context for AI-assisted development patterns, prompt injection awareness, and secret handling. | Partial. Documentation-based guidance exists. No formal training records or training completion tracking. |
| **GOVERN-6.1** | Policies and procedures for AI supply chain risk are established | `pip-audit` CI gate; `detect-secrets` pre-commit baseline; `ADR-016`; Epic 8 SBOM and ONNX integrity checks | Implemented for dependency risk and supply chain integrity. Formal Software Bill of Materials (SBOM) and model weight verification implemented in Epic 8 (`weight_integrity.py`). |

---

## MAP Function

The MAP function establishes context about how an AI system is intended to be used, who it affects, and what risks are present given that deployment context. Controls in this function answer: what is this system for, what could go wrong, and for whom?

| Sub-Category | Description | Artifact / Control | Implementation Status |
|---|---|---|---|
| **MAP-1.1** | Context of deployment is established | `README.md` — stated intended use (multi-agent workflow orchestration); `docs/ROADMAP.md` — versioned feature arcs; `docs/ARCHITECTURE.md` — high-level system boundaries; `docs/AI_RISK_MANAGEMENT.md` and `docs/OWASP_LLM_THREAT_MODEL.md` document risk boundaries and human-review expectations. | Implemented. Intended use, out-of-scope uses, and deployment context are documented. |
| **MAP-1.5** | Organizational risk tolerance is established | `docs/KNOWN_LIMITATIONS.md` — each known limitation carries an explicit status ("Accepted debt", "Accepted for v0.3.0", "Accepted — correct trade-off") and a workaround; `docs/adr/ADR-016` — explicit trade-off analysis for provider dependency vs. CI access; `docs/adr/ADR-001` — transitional architecture accepted as carrying cost | Partial. Risk tolerance is expressed as case-by-case ADR decisions and KNOWN_LIMITATIONS entries rather than a formal enterprise risk appetite statement. Honest and transparent for the portfolio context. |
| **MAP-2.1** | Risk from deployment context is assessed | `docs/KNOWN_LIMITATIONS.md` §4 (operational gaps — replay buffer, multi-process state inconsistency); `docs/adr/ADR-002` (provider failure risk — cascade analysis, bulkhead recommendations, half-open probe strategy); `docs/KNOWN_LIMITATIONS.md` §3.1 (CI provider dependency) | Implemented for known risk categories. No formal threat model document. An OWASP LLM Top 10 threat model is identified as a gap (see Gap Analysis). |
| **MAP-2.3** | Scientific integrity and organizational commitments are documented | 13 ADRs carry explicit tradeoff matrices with option comparisons; ADR-001 cites Temporal.io production data and Martin Fowler's Strangler Fig guidance; ADR-002 cites Google SRE Book Chapter 22; ADR-015 provides quantitative gate thresholds; `docs/KNOWN_LIMITATIONS.md` §5.1 explicitly flags that Epics 3/5/6 plans were retrospective, not prospective | Implemented. Decisions are grounded in cited sources with explicit alternatives considered. |
| **MAP-3.1** | Mapping of benefits and costs is conducted | `docs/adr/ADR-INDEX.md` implementation status table — implementation percentages are audited and honest (e.g., ADR-010 at ~10%, ADR-012 at ~10%); `docs/KNOWN_LIMITATIONS.md` — cost/risk of each limitation is stated; `ROADMAP.md` §1 — shipped epics with their stated outcomes | Partial. Benefits and costs are traceable through the ADR corpus and KNOWN_LIMITATIONS. No formal cost-benefit analysis document. |
| **MAP-5.1** | Practices for AI transparency and explainability are defined | `docs/adr/ADR-INDEX.md` — all ADRs are public with status, implementation percentages, and lineage chains; `docs/KNOWN_LIMITATIONS.md` — honest accounting of limitations (stated explicitly: "This is an honest accounting. Every item here is real, reproducible, and has shipped"); `CONTRIBUTING.md` — PR-required process with mandatory reviewer; `ROADMAP.md` — tombstone entry for Epic 4 explaining the deliberate numbering gap | Implemented. Transparency is a design principle in the documentation culture. No explainability tooling for LLM output (outputs are not interpreted by the platform — they pass through to callers). |

---

## MEASURE Function

The MEASURE function calls for analysis and assessment of AI risks — quantifying what can be quantified, establishing baselines, and monitoring ongoing behavior. Controls in this function answer: how do we know the system is behaving as expected, and how do we detect when it is not?

| Sub-Category | Description | Artifact / Control | Implementation Status |
|---|---|---|---|
| **MEASURE-1.1** | AI risk metrics are established | Time-to-first-span p95 SLO (ADR-015, 30-sample rolling window); streaming flake-rate gate (nightly.yml — 50× per night); 80% coverage floor (ci.yml); 60% UI coverage floor (vitest.config.ts); Playwright streaming gate (5× per PR) | Implemented for operational reliability metrics. No bias or fairness metrics. |
| **MEASURE-2.1** | Test, evaluation, validation, and verification (TEVV) practices are documented | `agentic-v2-eval/` — 8 YAML rubrics (default, agent, code, coding_standards, pattern, prompt_pattern, prompt_standard, quality); LLM judge scoring 0.0–10.0 per rubric dimension; BatchRunner, StreamingRunner, AsyncStreamingRunner; 112 test files in `agentic-workflows-v2/tests/`; 80% backend coverage gate; Playwright E2E gate | Implemented for unit/integration/E2E testing. Eval harness TEVV is partially implemented — ADR-010 (commit-driven A/B methodology) at ~10%, ADR-011 (API interface) at ~15%, ADR-012 (UI hub) at ~10%. See Gap Analysis. |
| **MEASURE-2.5** | AI system monitoring practices are in place | OTEL tracing (`agentic_v2/integrations/otel.py`, `agentic_v2/integrations/tracing.py`) — parent-child trace assertions in CI; time-to-first-span measurement committed to `observability/slo-first-span.json`; nightly 50× reliability run committed to `observability/slo-flake-rate.json`; SmartModelRouter EMA latency tracking (p50–p99), per-model circuit breaker state | Implemented for CI-level monitoring. No production APM deployment (no Prometheus, Grafana, or equivalent). OTEL instrumentation is present but requires external collector to produce dashboards. |
| **MEASURE-2.6** | Evaluation of impacts and bias is conducted | `agentic-v2-eval/rubrics/` — quality, agent, and coding_standards rubrics include assessments of output appropriateness; `docs/KNOWN_LIMITATIONS.md` — explicitly surfaces capability limits rather than overstating reliability; research gating: `coverage_score >= 0.80`, `source_quality_score >= 0.80` for research workflows | Partial. Rubric-based assessment exists for output quality. No automated bias detection, fairness metrics, or demographic impact analysis. The platform is infrastructure (orchestration), not a model — direct bias measurement is a responsibility of the LLM providers used downstream. |
| **MEASURE-2.8** | Risks from third-party AI systems are documented | `docs/adr/ADR-002` — per-provider bulkhead isolation, cascade failure analysis, adaptive cooldown; `docs/adr/ADR-016` — GitHub Models as default CI provider, explicit evaluation of credential-dependency trade-off; `docs/KNOWN_LIMITATIONS.md` §4.2 — multi-process stat inconsistency for SmartModelRouter (provider stats do not replicate across processes) | Partial. Provider risk is analyzed for availability and circuit behavior. No formal third-party AI system risk assessment (e.g., no documentation of what happens if a provider's model behavior changes unexpectedly). |
| **MEASURE-4.1** | Measurement results are documented | ADR-INDEX.md implementation audit percentages (last audited 2026-04-22); `observability/` SLO rolling window files committed after each nightly run; CI badge artifacts; coverage and test gates in CI configuration. | Implemented for most signals. No centralized measurement dashboard. |

---

## MANAGE Function

The MANAGE function focuses on prioritizing and addressing identified AI risks — treatment, response, and recovery. Controls in this function answer: when something goes wrong, what happens?

| Sub-Category | Description | Artifact / Control | Implementation Status |
|---|---|---|---|
| **MANAGE-1.1** | Response plans for identified risks are in place | `agentic-workflows-v2/SECURITY.md` — coordinated disclosure process, 3-day acknowledgment SLA, 7-day triage SLA; `docs/KNOWN_LIMITATIONS.md` — every known limitation has an explicit Status, Workaround, and Upstream fix field; `ROADMAP.md` Sprint B items are directly traceable to KNOWN_LIMITATIONS entries | Implemented. Response plans exist for security disclosures and for known operational limitations. No formal incident response runbook or escalation chain beyond SECURITY.md. |
| **MANAGE-1.3** | Risk controls are implemented and tested | `agentic_v2/middleware/sanitization.py` — prompt injection detection (PromptInjectionDetector), PII detection (PIIDetector), secret detection (SecretDetector), Unicode normalization (UnicodeSanitizer), SHA-256 audit trail hashing; `agentic_v2/contracts/sanitization.py` — hash-based immutable audit contracts; SmartModelRouter three-state circuit breaker with adaptive cooldown; tool allowlist DENY-by-default for high-risk operations; Epic 8 Controls: OIDC Authentication (`auth_oidc.py`), Tenant Isolation (`tenant.py`), and Append-Only Audit Logging (`audit_log.py`). | Implemented. Sanitization middleware, circuit breaker, and tool safety controls are tested (middleware tests in `tests/middleware/`). |
| **MANAGE-2.2** | Mechanisms for incident tracking are in place | `agentic-workflows-v2/SECURITY.md` — GitHub Security Advisory as the private incident intake channel; `docs/KNOWN_LIMITATIONS.md` — operational issues are tracked with upstream fix pointers; `CHANGELOG.md` — public record of changes per release including bug fixes | Partial. Incident tracking is GitHub Advisory + CHANGELOG. No formal incident management system (JIRA, ServiceNow). Appropriate for current project scale. |
| **MANAGE-2.4** | Decommission and retirement procedures are defined | `docs/adr/ADR-INDEX.md` — ADR-003 formally marked Superseded by ADR-007 with explicit lineage; `docs/ROADMAP.md` §1 — Epic 4 tombstone with `git log` verification command; `docs/KNOWN_LIMITATIONS.md` §6 — removal policy: "When a limitation is fixed, remove the entry and link the fix from CHANGELOG.md" | Partial. Supersession patterns exist for ADRs and features. No formal data retention or model retirement policy (platform does not store trained models — it routes to external providers). |
| **MANAGE-3.1** | Risk treatment decisions are documented | ADR corpus (13 records) — each ADR includes explicit Decision, Consequences (positive and negative), and Code-level recommendations; lineage chains in ADR-INDEX.md trace how decisions were refined (ADR-003 → ADR-007 → ADR-009 in the Research domain; ADR-010 → ADR-011 → ADR-012 in Evaluation domain); `docs/KNOWN_LIMITATIONS.md` — every entry includes a Status field indicating whether the risk was accepted, mitigated, or deferred | Implemented. Risk treatment reasoning is captured in ADR records with citations. |
| **MANAGE-4.1** | Residual risk is communicated | `docs/KNOWN_LIMITATIONS.md` — public, in-repo, honest accounting with no mitigation theater; `docs/adr/ADR-INDEX.md` — implementation percentages are audited and honest (e.g., ADR-010 at ~10% — the gap between decision and implementation is stated); `ROADMAP.md` Sprint B — residual debt is named and owner-less items are marked "unassigned" rather than hidden | Implemented. Residual risk communication is a design principle of the documentation approach. |

---

## Gap Analysis

The following gaps represent areas where the platform's engineering governance does not fully satisfy AI RMF expectations. This section is as important as the mapping above — honest gap analysis is a prerequisite for trust in federal AI delivery contexts.

### GAP-1: No formal threat model document

There is no OWASP LLM Top 10 threat model or equivalent structured threat analysis. Security-relevant controls exist (sanitization middleware, tool allowlists, DENY-by-default), but they are not organized into a threat model that maps attack surfaces to mitigations. The `docs/` directory does not contain an `OWASP_LLM_THREAT_MODEL.md` or equivalent.

**Risk:** A reviewer cannot assess the completeness of the security controls without constructing the threat model themselves.  
**Path to resolution:** Author `docs/OWASP_LLM_THREAT_MODEL.md` mapping OWASP LLM Top 10 categories to existing controls and identified gaps.

### GAP-2: No automated model output monitoring for drift or behavioral change

The platform routes to external LLM providers (OpenAI, Anthropic, Azure OpenAI, Gemini, GitHub Models). There is no mechanism to detect if a provider's underlying model changes behavior — e.g., a model version update that shifts output format, tone, or reasoning patterns. Rubric-based evaluation exists, but it runs on demand (not continuously against live traffic), and ADRs 010/011/012 for the full eval harness methodology are only 10–15% implemented.

**Risk:** Behavioral drift in upstream models could degrade workflow outputs before it is detected.  
**Path to resolution:** Implement CI-gated eval runs per ADR-010/011 proposal; add a canary evaluation workflow that runs the rubric suite against a fixed sample set on a schedule.

### GAP-3: No CUI/FOUO handling documentation

The platform targets federal/enterprise contexts but has no documentation covering Controlled Unclassified Information (CUI) or For Official Use Only (FOUO) data handling requirements. There is no data classification policy, no CUI marking guidance, and no documentation of what data categories are appropriate to process through external LLM providers.

**Risk:** A team deploying this platform in a federal context could inadvertently route CUI through commercial LLM APIs, violating NIST 800-171 and potentially ITAR/EAR requirements.  
**Path to resolution:** Author a CUI handling appendix covering: which workflow configurations are appropriate for which data classifications, how to configure `AGENTIC_NO_LLM=1` placeholder mode for offline/air-gapped contexts, and what provider attestations would be required before processing CUI.

### GAP-4: No formal Authorization to Operate (ATO) boundary document

This repository is not packaged as an RMF authorization boundary. There is no System Security Plan (SSP), Privacy Impact Assessment (PIA), or Authorization Boundary Diagram. These are prerequisites for operating in a federal information system context.

**Risk:** The platform cannot be used in a federally accredited information system without a separate ATO package being authored by the deploying agency.  
**Path to resolution:** This is intentional for a portfolio/prototype artifact. An ATO package would be authored by the deploying agency as part of their system authorization process, not by the platform itself.

### GAP-5: Eval framework implementation is substantially below proposal

ADR-010 (commit-driven A/B eval methodology), ADR-011 (eval API interface), and ADR-012 (UI evaluation hub) are Proposed status with implementation at ~10%, ~15%, and ~10% respectively. The eval harness runs on demand rather than being CI-gated against every commit. Rubric scoring exists but is not integrated into the PR gate.

**Risk:** The MEASURE function controls rely on a TEVV capability that is substantially aspirational rather than operational.  
**Path to resolution:** The gap is acknowledged in ADR-INDEX.md and ROADMAP.md. Full implementation is an Epic 7+ candidate.

### GAP-6: No structured output enforcement

The platform does not enforce structured output from LLM providers (no Instructor, Outlines, or equivalent). Agent outputs are parsed by each agent's implementation — there is no platform-level schema validation of LLM responses.

**Risk:** LLM providers can return malformed, inconsistent, or unexpected output that propagates as structured data. Each agent bears the burden of defensive parsing.  
**Path to resolution:** An ADR and prototype implementation for structured output enforcement has not been authored. This is a MEASURE and MANAGE gap.

### GAP-7: No Software Bill of Materials (SBOM)
**Status: Closed in Epic 8.** 
`cyclonedx-bom` SBOM generation and ONNX weight hash verification (`weight_integrity.py`) have been deployed, fulfilling federal software supply chain requirements (EO 14028).

---

## Relationship to Other Documents

| Document | Location | Relationship to This Document |
|---|---|---|
| Security Policy | `agentic-workflows-v2/SECURITY.md` | Primary source for MANAGE-1.1 and MANAGE-2.2 controls — disclosure process, response SLAs, hardening guidance |
| Known Limitations | `docs/KNOWN_LIMITATIONS.md` | Primary source for MAP-1.5, MAP-2.1, MANAGE-4.1 — honest risk register with workarounds and upstream fix pointers |
| ADR Index | `docs/adr/ADR-INDEX.md` | Primary source for GOVERN-1.1, MAP-2.3, MANAGE-3.1 — 13 decision records with lineage, implementation status, and audit dates |
| OWASP LLM Threat Model | `docs/OWASP_LLM_THREAT_MODEL.md` | Does not exist — identified as GAP-1. Would satisfy MAP-2.1 and MEASURE-2.8 when authored |
| Architecture Decision Records | `docs/adr/ADR-001` through `ADR-017` | Supporting evidence for MAP-2.3, GOVERN-1.7, MANAGE-3.1 — individual decision rationales with tradeoff matrices and cited sources |
| Coding Standards | `docs/CODING_STANDARDS.md` | Supporting evidence for GOVERN-1.1 — technical standards that operationalize the governance policies |
| Roadmap | `docs/ROADMAP.md` | Supporting evidence for MAP-1.1, MANAGE-2.4 — versioned capability arcs and Sprint B debt tracking |
| Changelog | `CHANGELOG.md` | Supporting evidence for MANAGE-2.2 — public change record per release |

---

## Summary Assessment

| Function | Coverage | Assessment |
|---|---|---|
| **GOVERN** | Substantial | Policies, gates, ADR process, and contribution workflow are mature. Accountability structures are lightweight (single maintainer) and appropriate for the current scale. The gap is formal RACI expansion for multi-team delivery. |
| **MAP** | Good | Intended use, deployment context, and risk tolerance are documented. ADR tradeoff matrices provide MAP-2.3 evidence. The gap is a structured threat model. |
| **MEASURE** | Moderate | Operational SLOs, E2E gates, and rubric-based eval exist. The gap is that the full eval harness (ADR-010/011/012) is substantially unimplemented, and there are no bias, fairness, or behavioral drift metrics. |
| **MANAGE** | Good | Security disclosure process, known-limitation tracking, and ADR risk treatment documentation are solid. The gaps are SBOM, CUI handling, and a formal incident runbook. |

This platform demonstrates consistent risk awareness across all four functions, with the largest technical gaps in MEASURE (eval harness completeness) and the largest policy gaps in CUI/FOUO handling and formal authorization boundary documentation. For federal deployment readiness, the CUI handling documentation (GAP-3) and OWASP threat model (GAP-1) are the highest-priority authoring tasks.
