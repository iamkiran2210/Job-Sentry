from datetime import timedelta

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings, settings
from app.core.exceptions import UnauthorizedException
from app.core.security import create_access_token, decode_token


def test_access_tokens_have_bounded_lifetime_and_validated_issuer_audience(monkeypatch):
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 60)
    token = create_access_token("user-id", "recruiter")
    payload = jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_exp": False, "verify_aud": False},
    )
    assert payload["exp"] - payload["iat"] <= 15 * 60
    assert payload["iss"] == settings.JWT_ISSUER
    assert payload["aud"] == settings.JWT_AUDIENCE
    assert decode_token(token)["sub"] == "user-id"

    wrong_audience = jwt.encode({**payload, "aud": "other"}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(UnauthorizedException):
        decode_token(wrong_audience)


@pytest.mark.parametrize("secret", ["", "short", "replace-with-a-very-secure-random-secret-key-at-least-32-chars"])
def test_production_settings_reject_missing_short_or_placeholder_secret(secret):
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(ENVIRONMENT="production", JWT_SECRET=secret, DEBUG=True)


def test_production_settings_force_debug_and_docs_off():
    configured = Settings(ENVIRONMENT="production", JWT_SECRET="s" * 40, DEBUG=True, DOCS_ENABLED=True)
    assert configured.DEBUG is False
    assert configured.DOCS_ENABLED is False


@pytest.mark.asyncio
async def test_security_headers_are_added_to_json_responses():
    from app.core.observability import SecurityHeadersMiddleware

    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/private")
    async def private():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/private")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_cors_rejects_origins_outside_the_configured_list(client):
    response = await client.get("/health", headers={"Origin": "http://localhost:9999"})
    assert "access-control-allow-origin" not in response.headers
