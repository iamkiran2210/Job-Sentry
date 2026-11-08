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

SENSITIVE_KEYS = ("authorization", "cookie", "password", "token", "secret", "api_key", "email", "phone", "resume", "body")


def current_request_id() -> str | None:
    return request_id_context.get()


def redact(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(secret in str(key).casefold() for secret in SENSITIVE_KEYS) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def scrub_report_event(event: dict) -> dict:
    """Keep event metadata while removing exception text and sensitive fields."""
    cleaned = redact(event)
    if isinstance(cleaned.get("exception"), dict):
        cleaned["exception"] = {"type": cleaned["exception"].get("type", "Error"), "value": "[REDACTED]"}
    if isinstance(cleaned.get("message"), str):
        cleaned["message"] = "[REDACTED]"
    return cleaned


class ErrorReporter(Protocol):
    def report_exception(self, exception: BaseException, *, request_id: str | None) -> None: ...


class NoOpErrorReporter:
    def report_exception(self, exception: BaseException, *, request_id: str | None) -> None:
        return None


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
            event = redact({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "level": "info", "event": "request_complete", "request_id": request_id,
                "user_id": state.get("user_id"), "company_id": state.get("company_id"),
                "method": scope.get("method"), "path": route_template,
                "status": status, "duration_ms": round((time.monotonic() - started) * 1000, 2),
            })
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
