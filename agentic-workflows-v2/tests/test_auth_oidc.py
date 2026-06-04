"""Tests for OIDC JWT authentication middleware."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI, Request
from starlette.testclient import TestClient

from agentic_v2.core.tenant import TenantContext, get_tenant_context
from agentic_v2.server.auth_oidc import OIDCAuthenticator, OIDCAuthMiddleware
from agentic_v2.settings import Settings, get_settings

ISSUER = "https://issuer.example/"
AUDIENCE = "agentic-api"
KID = "test-key-1"


@pytest.fixture()
def rsa_keypair() -> tuple[rsa.RSAPrivateKey, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": KID,
        "use": "sig",
        "alg": "RS256",
        "n": jwt.utils.base64url_encode(
            public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, "big")
        ).decode("ascii"),
        "e": jwt.utils.base64url_encode(
            public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, "big")
        ).decode("ascii"),
    }
    return private_key, {"keys": [jwk]}


@pytest.fixture()
def oidc_settings() -> Settings:
    get_settings.cache_clear()
    return Settings(
        agentic_oidc_enabled=True,
        agentic_oidc_issuer=ISSUER,
        agentic_oidc_audience=AUDIENCE,
        agentic_oidc_jwks_url="https://issuer.example/.well-known/jwks.json",
        agentic_oidc_leeway_seconds=0,
    )


def make_token(
    private_key: rsa.RSAPrivateKey,
    *,
    audience: str = AUDIENCE,
    issuer: str = ISSUER,
    expires_delta: timedelta = timedelta(minutes=5),
    subject: str = "user-123",
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": subject,
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + expires_delta,
    }
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": KID},
    )


def make_app(
    settings: Settings,
    jwks: dict[str, Any] | None = None,
    jwks_provider=None,
) -> FastAPI:
    app = FastAPI()
    authenticator = OIDCAuthenticator(
        settings=settings,
        jwks_provider=jwks_provider or (lambda: jwks),
    )
    app.add_middleware(
        OIDCAuthMiddleware,
        settings=settings,
        authenticator=authenticator,
    )

    @app.get("/api/protected")
    async def protected(request: Request):
        actor = request.state.auth_actor
        return {"subject": actor.subject, "auth_type": actor.auth_type}

    @app.get("/api/tenant")
    async def tenant(context: TenantContext = Depends(get_tenant_context)):
        return {"tenant_id": context.tenant_id, "source": context.source}

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    return app


def test_valid_oidc_token_passes(
    oidc_settings: Settings,
    rsa_keypair: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwks = rsa_keypair
    client = TestClient(make_app(oidc_settings, jwks))

    response = client.get(
        "/api/protected",
        headers={"Authorization": f"Bearer {make_token(private_key)}"},
    )

    assert response.status_code == 200
    assert response.json() == {"subject": "user-123", "auth_type": "oidc"}


def test_expired_oidc_token_is_rejected(
    oidc_settings: Settings,
    rsa_keypair: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwks = rsa_keypair
    client = TestClient(make_app(oidc_settings, jwks))

    response = client.get(
        "/api/protected",
        headers={
            "Authorization": f"Bearer {make_token(private_key, expires_delta=timedelta(minutes=-1))}"
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing bearer token"


def test_wrong_audience_oidc_token_is_rejected(
    oidc_settings: Settings,
    rsa_keypair: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwks = rsa_keypair
    client = TestClient(make_app(oidc_settings, jwks))

    response = client.get(
        "/api/protected",
        headers={
            "Authorization": f"Bearer {make_token(private_key, audience='other-api')}"
        },
    )

    assert response.status_code == 401


def test_missing_auth_is_rejected(
    oidc_settings: Settings,
    rsa_keypair: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    _private_key, jwks = rsa_keypair
    client = TestClient(make_app(oidc_settings, jwks))

    response = client.get("/api/protected")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_jwks_failure_returns_provider_unavailable(
    oidc_settings: Settings,
    rsa_keypair: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, _jwks = rsa_keypair

    def failing_jwks_provider():
        raise RuntimeError("jwks unavailable")

    client = TestClient(make_app(oidc_settings, jwks_provider=failing_jwks_provider))

    response = client.get(
        "/api/protected",
        headers={"Authorization": f"Bearer {make_token(private_key)}"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Authentication provider unavailable"


def test_api_key_fallback_passes_when_oidc_enabled(
    monkeypatch: pytest.MonkeyPatch,
    oidc_settings: Settings,
) -> None:
    monkeypatch.setenv("AGENTIC_API_KEY", "legacy-secret")
    get_settings.cache_clear()

    def failing_jwks_provider():
        raise RuntimeError("jwks unavailable")

    client = TestClient(make_app(oidc_settings, jwks_provider=failing_jwks_provider))

    response = client.get(
        "/api/protected",
        headers={"X-API-Key": "legacy-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"subject": "api-key", "auth_type": "api_key"}


def test_oidc_tenant_claim_is_exposed_to_tenant_context(
    oidc_settings: Settings,
    rsa_keypair: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    private_key, jwks = rsa_keypair
    client = TestClient(make_app(oidc_settings, jwks))

    response = client.get(
        "/api/tenant",
        headers={
            "Authorization": (
                "Bearer "
                + make_token(private_key, extra_claims={"tid": "tenant-from-jwt"})
            )
        },
    )

    assert response.status_code == 200
    assert response.json() == {"tenant_id": "tenant-from-jwt", "source": "oidc"}
