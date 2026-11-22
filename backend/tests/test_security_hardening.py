from uuid import uuid4

import jwt
import pytest
from app.core.config import Settings, settings
from app.core.exceptions import UnauthorizedException
from app.core.security import create_access_token, decode_token
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


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

    wrong_audience = jwt.encode(
        {**payload, "aud": "other"}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
    )
    with pytest.raises(UnauthorizedException):
        decode_token(wrong_audience)


@pytest.mark.parametrize(
    "secret", ["", "short", "replace-with-a-very-secure-random-secret-key-at-least-32-chars"]
)
def test_production_settings_reject_missing_short_or_placeholder_secret(secret):
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(ENVIRONMENT="production", JWT_SECRET=secret, DEBUG=True)


def test_production_settings_force_debug_and_docs_off():
    configured = Settings(
        ENVIRONMENT="production", JWT_SECRET="s" * 40, DEBUG=True, DOCS_ENABLED=True
    )
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


def test_only_documented_auth_and_liveness_routes_are_public():
    from app.main import app

    public_paths = {
        "/health",
        "/ready",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
    }
    schema = app.openapi()
    missing_security = sorted(
        f"{method.upper()} {path}"
        for path, operations in schema["paths"].items()
        for method, operation in operations.items()
        if method in {"get", "post", "put", "patch", "delete"}
        and path not in public_paths
        and not operation.get("security")
    )
    assert not missing_security, f"Routes missing authentication: {missing_security}"


def test_sentry_reporter_initializes_without_pii_and_scrubs_events():
    from contextlib import contextmanager

    from app.core.observability import build_error_reporter

    class Scope:
        def __init__(self):
            self.tags = {}

        def set_tag(self, name, value):
            self.tags[name] = value

    class FakeSentry:
        def __init__(self):
            self.options = None
            self.scope = Scope()
            self.exceptions = []

        def init(self, **options):
            self.options = options

        @contextmanager
        def push_scope(self):
            yield self.scope

        def capture_exception(self, exception):
            self.exceptions.append(exception)

    sentry = FakeSentry()
    reporter = build_error_reporter("https://example.invalid/123", sentry_sdk=sentry)
    reporter.report_exception(ValueError("secret resume text"), request_id="request-123")
    assert sentry.options["send_default_pii"] is False
    assert sentry.options["before_send"](
        {
            "message": "secret resume text",
            "exception": {"type": "ValueError", "value": "secret resume text"},
        },
        {},
    ) == {
               "message": "[REDACTED]",
               "exception": {"type": "ValueError", "value": "[REDACTED]"},
           }
    assert sentry.scope.tags == {"request_id": "request-123"}
    assert len(sentry.exceptions) == 1


@pytest.mark.asyncio
async def test_unhandled_exception_reports_request_id_without_logging_exception_text(
        monkeypatch, caplog
):
    from types import SimpleNamespace

    import app.core.exceptions as handlers

    class Reporter:
        captured = None

        def report_exception(self, exception, *, request_id):
            self.captured = (exception, request_id)

    reporter = Reporter()
    monkeypatch.setattr(handlers, "error_reporter", reporter)
    request_id = str(uuid4())
    request = SimpleNamespace(
        state=SimpleNamespace(request_id=request_id),
        method="GET",
        url=SimpleNamespace(path="/private"),
    )
    caplog.set_level("ERROR", logger="job_sentry")
    try:
        raise ValueError("private resume text")
    except ValueError as exc:
        response = await handlers.unhandled_exception_handler(request, exc)
    assert response.status_code == 500
    assert reporter.captured[0].args[0] == "private resume text"
    assert reporter.captured[1] == request_id
    assert "private resume text" not in caplog.text
    record = next(record for record in caplog.records if record.name == "job_sentry")
    assert record.request_id == request_id
    assert record.exception_type == "ValueError"
    assert record.traceback_frames
