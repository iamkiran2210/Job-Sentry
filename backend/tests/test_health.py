import json
from types import SimpleNamespace
from uuid import UUID
from uuid import uuid4

import pytest
from app.core.config import settings
from app.core.observability import (
    NoOpErrorReporter,
    redact,
    scrub_report_event,
    write_worker_heartbeat,
)
from app.modules.health import router as health_module


@pytest.mark.asyncio
async def test_request_id_is_echoed_logged_and_error_body_uses_same_id(client, caplog):
    caplog.set_level("INFO", logger="job_sentry.request")
    request_id = str(uuid4())
    response = await client.get("/health", headers={"X-Request-ID": request_id})
    assert response.headers["x-request-id"] == request_id
    generated = await client.get("/health")
    UUID(generated.headers["x-request-id"])

    unauthorized = await client.get("/api/v1/jobs", headers={"X-Request-ID": request_id})
    assert unauthorized.status_code == 401
    assert unauthorized.json()["request_id"] == request_id
    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "job_sentry.request"
    ]
    event = next(
        item for item in events if item["request_id"] == request_id and item["path"] == "/health"
    )
    assert event["status"] == 200
    assert "authorization" not in event and "duration_ms" in event


def test_redaction_masks_nested_secrets_and_pii():
    result = redact({"nested": {"email": "person@example.test", "api_key": "secret"}, "safe": "ok"})
    assert result == {"nested": {"email": "[REDACTED]", "api_key": "[REDACTED]"}, "safe": "ok"}
    event = scrub_report_event(
        {
            "message": "private exception",
            "exception": {"type": "ValueError", "value": "resume content"},
        }
    )
    assert event == {
        "message": "[REDACTED]",
        "exception": {"type": "ValueError", "value": "[REDACTED]"},
    }
    assert NoOpErrorReporter().report_exception(ValueError("private"), request_id="request") is None


@pytest.mark.asyncio
async def test_worker_heartbeat_sets_45_second_ttl():
    class Redis:
        async def set(self, key, value, ex):
            self.result = (key, value, ex)

    redis = Redis()
    await write_worker_heartbeat(redis, "celery@worker-1")
    assert redis.result == ("worker:heartbeat:celery@worker-1", "1", 45)


@pytest.mark.asyncio
async def test_health_is_liveness_only_and_returns_minimal_fields(monkeypatch):
    async def fail():
        raise AssertionError("liveness must not call dependencies")

    monkeypatch.setattr(health_module, "check_database", fail)
    monkeypatch.setattr(health_module, "check_redis", fail)
    request = SimpleNamespace(app=SimpleNamespace(version="1.0.0"))
    result = await health_module.health(request)
    assert result == {
        "status": "ok",
        "version": "1.0.0",
        "commit": settings.GIT_COMMIT or "unknown",
    }


class FakeRedis:
    closed = False

    async def scan_iter(self, match):
        assert match == "worker:heartbeat:*"
        yield b"worker:heartbeat:worker-a"

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_ready_reports_minimal_checks_and_degraded_missing_worker(monkeypatch):
    async def ok():
        return None

    client = FakeRedis()

    async def redis():
        return client

    monkeypatch.setattr(health_module, "check_database", ok)
    monkeypatch.setattr(health_module, "check_redis", redis)
    monkeypatch.setattr(health_module, "check_migration", ok)
    monkeypatch.setattr(health_module, "check_storage", ok)
    monkeypatch.setattr(health_module, "count_workers", lambda _: _one_worker())
    response = await health_module.ready()
    assert response.status_code == 200
    assert b"internal" not in response.body
    assert client.closed is True

    async def no_workers(_):
        return 0

    monkeypatch.setattr(health_module, "count_workers", no_workers)
    monkeypatch.setattr(settings, "READY_REQUIRE_WORKER", False)
    response = await health_module.ready()
    assert response.status_code == 200
    assert b'"workers":"degraded"' in response.body


async def _one_worker():
    return 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dependency", ["check_database", "check_migration", "check_storage", "check_redis"]
)
async def test_ready_returns_503_without_dependency_details(monkeypatch, dependency):
    async def fail():
        raise RuntimeError(f"private failure {uuid4()}")

    async def ok():
        return None

    class EmptyRedis:
        async def scan_iter(self, match):
            if False:
                yield None

        async def aclose(self):
            return None

    monkeypatch.setattr(health_module, "check_database", ok)
    monkeypatch.setattr(health_module, "check_migration", ok)
    monkeypatch.setattr(health_module, "check_storage", ok)
    monkeypatch.setattr(health_module, "check_redis", lambda: _redis_or_fail(dependency, fail))
    if dependency != "check_redis":
        monkeypatch.setattr(health_module, dependency, fail)
        monkeypatch.setattr(health_module, "check_redis", lambda: _return_redis(EmptyRedis()))
    response = await health_module.ready()
    assert response.status_code == 503
    assert b"private failure" not in response.body
    assert b"traceback" not in response.body


async def _redis_or_fail(dependency, fail):
    if dependency == "check_redis":
        await fail()
    return object()


async def _return_redis(client):
    return client
