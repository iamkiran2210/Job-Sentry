"""Request context, structured request logging, and safe field redaction."""

from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar
from typing import Protocol
from uuid import UUID, uuid4

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
logger = logging.getLogger("job_sentry.request")

SENSITIVE_KEYS = (
    "authorization",
    "cookie",
    "password",
    "token",
    "secret",
    "api_key",
    "email",
    "phone",
    "resume",
    "body",
)


def current_request_id() -> str | None:
    return request_id_context.get()


def redact(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if any(secret in str(key).casefold() for secret in SENSITIVE_KEYS)
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def scrub_report_event(event: dict, hint: dict | None = None) -> dict:
    """Keep event metadata while removing exception text and sensitive fields."""
    cleaned = redact(event)
    if isinstance(cleaned.get("exception"), dict):
        cleaned["exception"] = {
            "type": cleaned["exception"].get("type", "Error"),
            "value": "[REDACTED]",
        }
    if isinstance(cleaned.get("message"), str):
        cleaned["message"] = "[REDACTED]"
    return cleaned


class ErrorReporter(Protocol):
    def report_exception(self, exception: BaseException, *, request_id: str | None) -> None: ...


class NoOpErrorReporter:
    def report_exception(self, exception: BaseException, *, request_id: str | None) -> None:
        return None


class SentryErrorReporter:
    def __init__(self, sentry_sdk) -> None:
        self._sentry_sdk = sentry_sdk

    def report_exception(self, exception: BaseException, *, request_id: str | None) -> None:
        with self._sentry_sdk.push_scope() as scope:
            if request_id:
                scope.set_tag("request_id", request_id)
            self._sentry_sdk.capture_exception(exception)


def build_error_reporter(dsn: str | None, *, sentry_sdk=None) -> ErrorReporter:
    if not dsn:
        return NoOpErrorReporter()
    if sentry_sdk is None:
        import sentry_sdk as sentry_client

        sentry_sdk = sentry_client
    sentry_sdk.init(dsn=dsn, send_default_pii=False, before_send=scrub_report_event)
    return SentryErrorReporter(sentry_sdk)


async def write_worker_heartbeat(redis, hostname: str) -> None:
    await redis.set(f"worker:heartbeat:{hostname}", "1", ex=45)


class StructuredRequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = self._request_id(scope.get("headers", []))
        token = request_id_context.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.monotonic()
        status = 500

        async def send_with_request_id(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            route = scope.get("route")
            route_template = getattr(route, "path", "<unmatched>")
            state = scope.get("state", {})
            event = redact(
                {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "level": "info",
                    "event": "request_complete",
                    "request_id": request_id,
                    "user_id": state.get("user_id"),
                    "company_id": state.get("company_id"),
                    "method": scope.get("method"),
                    "path": route_template,
                    "status": status,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                }
            )
            logger.info(json.dumps(event, separators=(",", ":")))
            request_id_context.reset(token)

    @staticmethod
    def _request_id(headers) -> str:
        for key, value in headers:
            if key.lower() == b"x-request-id":
                try:
                    return str(UUID(value.decode("ascii")))
                except (ValueError, UnicodeDecodeError):
                    break
        return str(uuid4())


class SecurityHeadersMiddleware:
    """Add browser safety headers and prevent caching of JSON API responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {key.lower() for key, _ in headers}
                additions = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                ]
                content_type = next(
                    (value for key, value in headers if key.lower() == b"content-type"), b""
                )
                if content_type.startswith(b"application/json"):
                    additions.append((b"cache-control", b"no-store"))
                headers.extend((key, value) for key, value in additions if key not in existing)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
