"""Centralised application settings.

All environment variable reads for agentic_v2 core modules go through this
module.  Uses pydantic-settings so the app fails fast at startup when a
required variable is missing, and so that precedence is documented in one
place.

Precedence (highest to lowest):
1. Actual environment variables (``os.environ``)
2. ``.env`` file at the repo root (loaded by pydantic-settings automatically)
3. Defaults defined on the ``Settings`` class

Usage::

    from agentic_v2.settings import get_settings

    settings = get_settings()
    if settings.agentic_tracing:
        ...
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)

_TRUE_LITERALS = frozenset({"1", "true", "yes", "on"})
_FALSE_LITERALS = frozenset({"", "0", "false", "no", "off"})


def _coerce_env_flag(raw: Any, *, var_name: str) -> bool:
    """Coerce a bool-ish env var value without raising validation errors."""
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    value = str(raw).strip().lower()
    if value in _TRUE_LITERALS:
        return True
    if value in _FALSE_LITERALS:
        return False
    logger.warning(
        "%s=%r not recognised; treating as False. Accepted: %s (True) or %s (False).",
        var_name,
        raw,
        sorted(_TRUE_LITERALS),
        sorted(_FALSE_LITERALS),
    )
    return False


def is_agentic_no_llm_enabled() -> bool:
    """Read ``AGENTIC_NO_LLM`` directly from the live environment.

    This avoids stale `lru_cache` interactions when tests or long-lived
    processes flip the flag between calls.
    """
    return _coerce_env_flag(os.environ.get("AGENTIC_NO_LLM"), var_name="AGENTIC_NO_LLM")


class Settings(BaseSettings):
    """Typed application settings sourced from environment variables.

    Precedence: env vars > .env file > field defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_ignore_empty=True,
    )

    # --- OTEL / tracing ---
    agentic_tracing: bool = Field(default=False, description="Enable OTLP tracing")
    agentic_metrics: bool = Field(
        default=False,
        description=(
            "Enable Prometheus metrics scrape endpoint at /metrics. "
            "Requires opentelemetry-exporter-prometheus (bundled in the "
            "[tracing] install extra). Set AGENTIC_METRICS=1 to activate."
        ),
    )
    agentic_trace_sensitive: bool = Field(
        default=False, description="Include prompt/response content in traces"
    )
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4317", description="OTLP exporter endpoint"
    )
    otel_exporter_otlp_protocol: str = Field(
        default="grpc", description="OTLP protocol: grpc or http/protobuf"
    )
    otel_service_name: str = Field(
        default="agentic-workflows-v2", description="Service name for traces"
    )

    # --- Agent loader ---
    agentic_external_agents_dir: str | None = Field(
        default=None, description="Directory containing external agent definitions"
    )

    # --- Runtime ---
    shell: str = Field(default="/bin/bash", description="Shell for subprocess execution")

    # --- LLM placeholder mode ---
    agentic_no_llm: bool = Field(
        default=False,
        description=(
            "When true, get_client() and get_chat_model() both install a "
            "deterministic placeholder so demos and CI can run without API "
            "keys. The native-engine path (get_client()) has no extra "
            "dependencies. The LangChain-adapter path (get_chat_model()) "
            "still requires the [langchain] install extra — without it, "
            "get_chat_model() raises ImportError even under the flag. "
            "Accepted string values (case-insensitive): '1'/'true'/'yes'/"
            "'on' are True; ''/'0'/'false'/'no'/'off' are False; unknown "
            "values are coerced to False with a logged warning. See "
            "docs/NO_LLM_MODE.md."
        ),
    )

    # --- ADR-023 Phase 5b: EK provider hot-path switch ---
    agentic_ek_provider: bool = Field(
        default=False,
        description=(
            "ADR-023 Option A hot-path switch. When true, "
            "LLMClientWrapper.complete() routes through the ExecutionKit "
            "LLMProvider shim (SmartRouterProvider -> backend.complete_chat) "
            "instead of the legacy text complete() path. DEFAULT OFF "
            "(opt-in via AGENTIC_EK_PROVIDER=1). P7 briefly flipped this to "
            "default-on (2026-05-31) but it was reverted the same day: "
            "default-on exposed two blockers tracked in ADR-023-migration-notes "
            "(an AGENTIC_EK_PROVIDER + get_settings lru_cache test-isolation "
            "leak, and a hang in the EK-default path). The EK path is "
            "fully functional opt-in; default-on resumes once both are fixed. "
            "Accepted string values mirror AGENTIC_NO_LLM: "
            "'1'/'true'/'yes'/'on' are True; ''/'0'/'false'/'no'/'off' are "
            "False; unknown values are coerced to False with a logged warning."
        ),
    )

    @field_validator("agentic_ek_provider", mode="before")
    @classmethod
    def _coerce_ek_provider_flag(cls, v: Any) -> bool:
        """Normalise ``AGENTIC_EK_PROVIDER`` env values.

        Mirrors :meth:`_coerce_no_llm_flag` so an unusual string never
        surfaces as an opaque ``ValidationError`` at the first LLM call;
        unrecognised values fall back to ``False`` (legacy path) with a
        logged warning so operators find out via the log, not a crash.
        """
        if isinstance(v, bool):
            return v
        if v is None:
            return False
        s = str(v).strip().lower()
        if s in _TRUE_LITERALS:
            return True
        if s in _FALSE_LITERALS:
            return False
        logger.warning(
            "AGENTIC_EK_PROVIDER=%r not recognised; treating as False "
            "(legacy path). Accepted: %s (True) or %s (False).",
            v,
            sorted(_TRUE_LITERALS),
            sorted(_FALSE_LITERALS),
        )
        return False

    # --- Governance: human approval gates (P1 #12) ---
    agentic_require_tool_approval: bool = Field(
        default=False,
        description=(
            "Global human-approval override. When TRUE, EVERY tool call is "
            "gated by the registered ApprovalProvider before it executes "
            "(see agentic_v2.governance.approval). DEFAULT OFF so existing "
            "flows are unaffected — the real default posture change comes from "
            "the per-tool requires_approval=True flags on high-impact builtins "
            "(shell/shell_exec/execute_python, file_write/file_delete/"
            "file_move/file_copy/directory_create, http/http_post), which gate "
            "those tools regardless of this flag. FAIL-CLOSED: a gated tool "
            "with no provider registered is DENIED, never executed."
        ),
    )
    agentic_approval_required_tools: str = Field(
        default="",
        description=(
            "Comma-separated extra tool names to gate behind human approval, "
            "in addition to the per-tool requires_approval flags. Example: "
            "'git_commit,deploy'. Empty by default (no extra tools gated). "
            "Whitespace around names is ignored. Like all approval triggers, "
            "this is OR'd with the per-tool flag and the global "
            "AGENTIC_REQUIRE_TOOL_APPROVAL override."
        ),
    )

    # --- Security: agent-loop sanitization ---
    agentic_sanitize_agent_loop: bool = Field(
        default=True,
        description=(
            "Attach inbound/outbound sanitization to the shared LLM client "
            "returned by models.get_client(), so per-step agent-loop calls — "
            "including tool outputs and retrieved content fed back to the "
            "model (the indirect prompt-injection vector) — are guarded, not "
            "just the HTTP request boundary. DEFAULT ON. Skipped automatically "
            "under AGENTIC_NO_LLM (placeholder mode). Set "
            "AGENTIC_SANITIZE_AGENT_LOOP=0 to disable. Accepted string values "
            "mirror AGENTIC_NO_LLM; unrecognised values fail safe to True so "
            "sanitization stays on."
        ),
    )

    @field_validator("agentic_sanitize_agent_loop", mode="before")
    @classmethod
    def _coerce_sanitize_agent_loop_flag(cls, v: Any) -> bool:
        """Normalise ``AGENTIC_SANITIZE_AGENT_LOOP``, failing safe to True.

        Unlike the other bool flags this defaults to ON, so an unset or
        unrecognised value must resolve to ``True`` (keep sanitization on)
        rather than the ``False`` that :func:`_coerce_env_flag` returns.
        """
        if isinstance(v, bool):
            return v
        if v is None:
            return True
        s = str(v).strip().lower()
        if s in _TRUE_LITERALS:
            return True
        if s in _FALSE_LITERALS:
            return False
        logger.warning(
            "AGENTIC_SANITIZE_AGENT_LOOP=%r not recognised; treating as True "
            "(fail-safe — sanitization stays on). Accepted: %s (True) or %s "
            "(False).",
            v,
            sorted(_TRUE_LITERALS),
            sorted(_FALSE_LITERALS),
        )
        return True

    @field_validator("agentic_no_llm", mode="before")
    @classmethod
    def _coerce_no_llm_flag(cls, v: Any) -> bool:
        """Normalise ``AGENTIC_NO_LLM`` env values.

        Pydantic's default bool parser raises ``ValidationError`` on
        unusual strings (``"2"``, stray whitespace, ``"yes"`` in some
        versions), which would surface as an opaque traceback at the
        first LLM call.  We accept the conservative set of literals
        documented in the field description and coerce everything else
        to ``False`` with a warning so operators find out via the log,
        not via a crash (Sprint B #5 follow-up review P2).
        """
        return _coerce_env_flag(v, var_name="AGENTIC_NO_LLM")

    # --- Logging ---
    log_format: str = Field(
        default="text",
        description="Log output format: 'text' (default) or 'json'",
    )
    audit_log_enabled: bool = Field(
        default=False,
        description="Enable tamper-evident audit logging for auth and workflow events.",
    )
    audit_log_backend: str = Field(
        default="file",
        description="Audit log backend: 'file' or 'redis'.",
    )
    audit_log_file_path: str = Field(
        default=".agentic_audit.jsonl",
        description="JSONL file path for append-only audit records.",
    )
    audit_log_redis_stream: str = Field(
        default="agentic:audit",
        description="Redis Stream key for audit records when audit_log_backend='redis'.",
    )
    audit_log_max_events: int = Field(
        default=10000,
        description="Maximum audit events retained by bounded backends such as Redis.",
    )

    @field_validator("log_format", mode="before")
    @classmethod
    def _validate_log_format(cls, v: Any) -> str:
        """Ensure log_format is either 'text' or 'json'."""
        if v is None:
            return "text"
        s = str(v).strip().lower()
        if s not in {"text", "json"}:
            logger.warning(
                "LOG_FORMAT=%r not recognised; treating as 'text'. "
                "Accepted values: 'text' or 'json'.",
                v,
            )
            return "text"
        return s

    @field_validator("audit_log_backend", mode="before")
    @classmethod
    def _validate_audit_log_backend(cls, v: Any) -> str:
        """Ensure audit_log_backend is either 'file' or 'redis'."""
        if v is None:
            return "file"
        s = str(v).strip().lower()
        if s not in {"file", "redis"}:
            logger.warning(
                "AUDIT_LOG_BACKEND=%r not recognised; treating as 'file'. "
                "Accepted values: 'file' or 'redis'.",
                v,
            )
            return "file"
        return s

    # --- HTTP API authentication: OIDC JWT verifier ---
    agentic_oidc_enabled: bool = Field(
        default=False,
        description="Enable OIDC JWT bearer-token authentication for HTTP API routes",
    )
    agentic_oidc_issuer: str | None = Field(
        default=None,
        description="Expected JWT issuer URL when OIDC auth is enabled",
    )
    agentic_oidc_audience: str | None = Field(
        default=None,
        description="Expected JWT audience when OIDC auth is enabled",
    )
    agentic_oidc_jwks_url: str | None = Field(
        default=None,
        description="OIDC JWKS URL used to resolve JWT signing keys",
    )
    # NoDecode keeps pydantic-settings from JSON-decoding the env value (a
    # bare "RS256,HS256" is not JSON); the before-validator below does the
    # comma split instead. The declared type stays list[str] so downstream
    # consumers (e.g. PyJWT's algorithms=...) never see a raw string.
    agentic_oidc_algorithms: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["RS256"],
        description="Comma-separated JWT signing algorithm allowlist",
    )
    agentic_oidc_jwks_cache_seconds: int = Field(
        default=300,
        description="JWKS cache TTL in seconds",
    )
    agentic_oidc_jwks_timeout_seconds: float = Field(
        default=5.0,
        description="Timeout in seconds for JWKS fetches",
    )
    agentic_oidc_leeway_seconds: int = Field(
        default=60,
        description="Allowed JWT clock skew in seconds for exp/nbf validation",
    )

    @field_validator("agentic_oidc_algorithms", mode="before")
    @classmethod
    def _parse_oidc_algorithms(cls, v: Any) -> list[str]:
        """Parse ``AGENTIC_OIDC_ALGORITHMS`` as a comma-separated allowlist."""
        if v is None:
            return ["RS256"]
        if isinstance(v, str):
            values = [item.strip() for item in v.split(",") if item.strip()]
            return values or ["RS256"]
        if isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()]
        return ["RS256"]

    # --- Tool: file operations ---
    agentic_file_base_dir: str | None = Field(
        default=None, description="Base directory for file operations (sandbox root)"
    )

    # --- Tool: HTTP operations ---
    agentic_block_private_ips: bool = Field(
        default=True,
        description=(
            "Block HTTP requests to private/loopback IPs (SSRF protection). "
            "Default ON — set AGENTIC_BLOCK_PRIVATE_IPS=0 to opt out (not recommended "
            "unless workflows legitimately reach internal services and you have applied "
            "compensating network-layer controls)."
        ),
    )

    # --- Tool: memory operations ---
    agentic_memory_path: str | None = Field(
        default=None, description="Path to persistent memory store"
    )

    # --- MCP ---
    max_mcp_output_tokens: int | None = Field(
        default=None, description="Token budget cap for MCP tool output"
    )

    # --- Redis shared state ---
    redis_url: str | None = Field(
        default=None,
        description=(
            "Redis URL for shared state across workers "
            "(e.g. 'redis://localhost:6379/0'). When set, SmartModelRouter "
            "persists circuit breaker state to Redis for cross-worker "
            "consistency. When unset, falls back to local file persistence."
        ),
    )
    redis_circuit_breaker_prefix: str = Field(
        default="agentic:cb:",
        description="Redis key prefix for circuit breaker state",
    )
    redis_circuit_breaker_ttl: int = Field(
        default=3600,
        description="TTL in seconds for circuit breaker keys in Redis (default 1h)",
    )

    # --- WebSocket replay store ---
    replay_store_backend: str = Field(
        default="auto",
        description=(
            "Replay store backend for WebSocket event history: "
            "'redis' (requires redis_url), 'sqlite' (requires aiosqlite), "
            "'memory' (in-process, no persistence), or 'auto' "
            "(tries redis → sqlite → memory in order of availability)."
        ),
    )
    replay_store_ttl: int = Field(
        default=14400,
        description="TTL in seconds for replay event keys in Redis (default 4 hours).",
    )
    replay_store_max_events: int = Field(
        default=500,
        description="Maximum events retained per run in the replay buffer.",
    )
    replay_sqlite_path: str = Field(
        default=".agentic_replay.db",
        description="Filesystem path for the SQLite replay store database file.",
    )

    # --- LangGraph checkpointing ---
    agentic_checkpointer_url: str | None = Field(
        default=None,
        description=(
            "PostgreSQL connection URL for LangGraph checkpointing "
            "(e.g. 'postgresql://user:pass@host:5432/db'). "
            "When set, WorkflowRunner uses AsyncPostgresSaver instead of the "
            "default in-memory MemorySaver.  Requires the [postgres] extra: "
            "pip install 'agentic-workflows-v2[postgres]'."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()
