"""OIDC JWT authentication middleware for the Agentic server.

This module adds opt-in OAuth2/OIDC bearer-token authentication for HTTP API
routes. It validates RS256 JWT access tokens against a configured issuer,
audience, and JWKS endpoint while preserving the legacy ``AGENTIC_API_KEY``
fallback.
"""

from __future__ import annotations

import inspect
import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

import httpx
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from ..settings import Settings, get_settings
from .auth import (
    _get_api_key,
    _get_auth_throttle_singleton,
    extract_http_token,
    is_public_path,
    is_token_authorized,
)
from .audit_log import audit_auth_request_event

if TYPE_CHECKING:
    from fastapi import Request

logger = logging.getLogger(__name__)

JWKSProvider = Callable[[], dict[str, Any]]


class OIDCConfigurationError(ValueError):
    """Raised when OIDC auth is enabled without required settings."""


class OIDCAuthenticationError(ValueError):
    """Raised when a JWT is missing, malformed, or rejected."""


class OIDCProviderUnavailable(RuntimeError):
    """Raised when JWKS cannot be loaded and no cached keys are available."""


@dataclass(frozen=True)
class AuthenticatedActor:
    """Safe request actor metadata derived from a validated credential."""

    auth_type: str
    subject: str
    issuer: str | None = None
    audience: str | None = None
    tenant_id: str | None = None
    organization_id: str | None = None

    def to_request_user(self) -> dict[str, Any]:
        """Return non-sensitive request user metadata for downstream deps."""
        claims: dict[str, str] = {}
        if self.tenant_id:
            claims["tenant_id"] = self.tenant_id
        if self.organization_id:
            claims["org_id"] = self.organization_id
        return {
            "auth_type": self.auth_type,
            "subject": self.subject,
            "issuer": self.issuer,
            "audience": self.audience,
            "tenant_id": self.tenant_id,
            "organization_id": self.organization_id,
            "claims": claims,
        }


def validate_oidc_settings(settings: Settings) -> None:
    """Fail fast when OIDC is enabled without required verifier settings."""
    if not settings.agentic_oidc_enabled:
        return

    missing = [
        name
        for name, value in {
            "AGENTIC_OIDC_ISSUER": settings.agentic_oidc_issuer,
            "AGENTIC_OIDC_AUDIENCE": settings.agentic_oidc_audience,
            "AGENTIC_OIDC_JWKS_URL": settings.agentic_oidc_jwks_url,
        }.items()
        if not value
    ]
    if missing:
        raise OIDCConfigurationError(
            "OIDC auth is enabled but required settings are missing: "
            + ", ".join(missing)
        )


class OIDCAuthenticator:
    """Validate OIDC JWTs against JWKS, issuer, and audience settings."""

    def __init__(
        self,
        settings: Settings | None = None,
        jwks_provider: JWKSProvider | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or get_settings()
        validate_oidc_settings(self.settings)
        self._jwks_provider = jwks_provider
        self._clock = clock
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_cached_at = 0.0

    async def authenticate(self, token: str) -> AuthenticatedActor:
        """Validate *token* and return safe actor metadata."""
        jwt_module = _import_pyjwt()
        try:
            header = jwt_module.get_unverified_header(token)
        except jwt_module.InvalidTokenError as exc:
            raise OIDCAuthenticationError("Malformed bearer token") from exc

        algorithm = header.get("alg")
        if algorithm not in self.settings.agentic_oidc_algorithms:
            raise OIDCAuthenticationError("Unsupported token signing algorithm")

        kid = header.get("kid")
        if not kid:
            raise OIDCAuthenticationError("Token header is missing kid")

        jwks = await self._get_jwks()
        key = self._select_key(jwks, kid)

        try:
            claims = jwt_module.decode(
                token,
                key=key,
                algorithms=self.settings.agentic_oidc_algorithms,
                audience=self.settings.agentic_oidc_audience,
                issuer=self.settings.agentic_oidc_issuer,
                leeway=self.settings.agentic_oidc_leeway_seconds,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt_module.ExpiredSignatureError as exc:
            raise OIDCAuthenticationError("Bearer token has expired") from exc
        except jwt_module.InvalidTokenError as exc:
            raise OIDCAuthenticationError("Bearer token validation failed") from exc

        subject = _claim_to_string(claims.get("sub"))
        if not subject:
            raise OIDCAuthenticationError("Bearer token is missing subject")

        return AuthenticatedActor(
            auth_type="oidc",
            subject=subject,
            issuer=_claim_to_string(claims.get("iss")),
            audience=_claim_to_string(claims.get("aud")),
            tenant_id=_first_claim_to_string(
                claims,
                ("tenant_id", "tenant", "tid"),
            ),
            organization_id=_first_claim_to_string(
                claims,
                ("org_id", "organization_id", "organization"),
            ),
        )

    async def _get_jwks(self) -> dict[str, Any]:
        now = self._clock()
        cache_ttl = self.settings.agentic_oidc_jwks_cache_seconds
        if self._jwks_cache is not None and now - self._jwks_cached_at < cache_ttl:
            return self._jwks_cache

        try:
            jwks = await self._load_jwks()
        except Exception as exc:
            if self._jwks_cache is not None:
                logger.warning("OIDC JWKS refresh failed; using cached JWKS")
                return self._jwks_cache
            raise OIDCProviderUnavailable("OIDC JWKS could not be loaded") from exc

        if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
            raise OIDCProviderUnavailable("OIDC JWKS response is invalid")

        self._jwks_cache = jwks
        self._jwks_cached_at = now
        return jwks

    async def _load_jwks(self) -> dict[str, Any]:
        if self._jwks_provider is not None:
            result = self._jwks_provider()
            if inspect.isawaitable(result):
                result = await result
            return result

        timeout = self.settings.agentic_oidc_jwks_timeout_seconds
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.get(str(self.settings.agentic_oidc_jwks_url))
            response.raise_for_status()
            return response.json()

    def _select_key(self, jwks: dict[str, Any], kid: str) -> Any:
        jwt_module = _import_pyjwt()
        for jwk in jwks.get("keys", []):
            if jwk.get("kid") == kid:
                return jwt_module.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        raise OIDCAuthenticationError("No matching JWKS key for bearer token")


class OIDCAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate protected API requests with OIDC JWT or API-key fallback."""

    def __init__(
        self,
        app,
        settings: Settings | None = None,
        authenticator: OIDCAuthenticator | None = None,
    ) -> None:
        super().__init__(app)
        self.settings = settings or get_settings()
        self.authenticator = authenticator or OIDCAuthenticator(self.settings)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        if is_public_path(request.url.path):
            return await call_next(request)

        token = extract_http_token(request)
        api_key = _get_api_key()
        client_host = request.client.host if request.client else "unknown"
        throttle = _resolve_throttle(request)

        is_locked, retry_after = throttle.is_locked(client_host)
        if is_locked:
            logger.warning(
                "OIDC auth throttle: rejecting locked IP %s (retry after %.0fs)",
                client_host,
                retry_after,
            )
            return _throttle_response(retry_after)

        if token is None:
            logger.warning(
                "OIDC authentication missing for %s from %s",
                request.url.path,
                client_host,
            )
            return _record_failure_and_respond(throttle, client_host)

        if api_key is not None and is_token_authorized(token.value, api_key):
            actor = AuthenticatedActor(
                auth_type="api_key",
                subject="api-key",
            )
            request.state.auth_actor = actor
            request.state.user = actor.to_request_user()
            throttle.record_success(client_host)
            await audit_auth_request_event(
                request=request,
                event_type="auth.api_key.succeeded",
                outcome="success",
                metadata={"subject": "api-key"},
            )
            return await call_next(request)

        if token.source != "authorization":
            logger.warning(
                "OIDC authentication failed for %s from %s",
                request.url.path,
                client_host,
            )
            await audit_auth_request_event(
                request=request,
                event_type="auth.oidc.failed",
                outcome="failure",
                metadata={"reason": "missing_or_invalid_token_source"},
            )
            return _record_failure_and_respond(throttle, client_host)

        try:
            actor = await self.authenticator.authenticate(token.value)
            request.state.auth_actor = actor
            request.state.user = actor.to_request_user()
            await audit_auth_request_event(
                request=request,
                event_type="auth.oidc.succeeded",
                outcome="success",
                metadata={"subject": actor.subject},
            )
        except OIDCProviderUnavailable:
            logger.exception(
                "OIDC provider unavailable while authenticating %s",
                request.url.path,
            )
            return JSONResponse(
                status_code=503,
                content={"detail": "Authentication provider unavailable"},
            )
        except OIDCAuthenticationError:
            logger.warning(
                "OIDC authentication failed for %s from %s",
                request.url.path,
                client_host,
            )
            await audit_auth_request_event(
                request=request,
                event_type="auth.oidc.failed",
                outcome="failure",
                metadata={"reason": "invalid_jwt_claims_or_signature"},
            )
            return _record_failure_and_respond(throttle, client_host)

        throttle.record_success(client_host)
        return await call_next(request)


def _auth_error_response() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": "Invalid or missing bearer token"},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _record_failure_and_respond(throttle, client_host: str) -> JSONResponse:
    throttle.record_failure(client_host)
    is_locked, retry_after = throttle.is_locked(client_host)
    if is_locked:
        return _throttle_response(retry_after)
    return _auth_error_response()


def _throttle_response(retry_after_seconds: float) -> JSONResponse:
    retry_int = max(1, int(retry_after_seconds))
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Too many failed authentication attempts. Please retry later.",
            "retry_after": retry_int,
        },
        headers={"Retry-After": str(retry_int)},
    )


def _resolve_throttle(request: Request):
    try:
        return request.app.state.auth_throttle
    except AttributeError:
        return _get_auth_throttle_singleton()


def _claim_to_string(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    if value is None:
        return None
    return str(value)


def _first_claim_to_string(
    claims: dict[str, Any],
    keys: tuple[str, ...],
) -> str | None:
    for key in keys:
        value = _claim_to_string(claims.get(key))
        if value:
            return value
    return None


def _import_pyjwt():
    try:
        import jwt
    except ImportError as exc:
        raise OIDCConfigurationError(
            "PyJWT is required for OIDC auth. Install the server extra."
        ) from exc
    return jwt
