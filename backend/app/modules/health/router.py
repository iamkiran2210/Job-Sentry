"""Liveness and readiness endpoints with minimal public responses."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.ai_features.resumes.config import get_settings as get_resume_settings
from app.core.config import settings
from app.core.database import engine

router = APIRouter(tags=["Health"])


async def check_database() -> None:
    async def ping():
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    await asyncio.wait_for(ping(), timeout=2)


async def check_redis() -> Any:
    from redis.asyncio import Redis

    client = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
    try:
        await asyncio.wait_for(client.ping(), timeout=2)
        return client
    except Exception:
        await client.aclose()
        raise


async def check_migration() -> None:
    root = Path(__file__).resolve().parents[3]
    expected = ScriptDirectory(str(root / "migrations")).get_current_head()
    async def current_revision():
        async with engine.connect() as connection:
            return (await connection.execute(
                text("SELECT version_num FROM job_sentry.alembic_version")
            )).scalar_one_or_none()
    current = await asyncio.wait_for(current_revision(), timeout=2)
    if current != expected:
        raise RuntimeError("database migration revision differs from application head")


async def check_storage() -> None:
    storage = Path(get_resume_settings().local_storage_dir)
    if not storage.is_dir():
        raise OSError("storage directory is unavailable")
    with tempfile.NamedTemporaryFile(dir=storage, prefix=".ready-", delete=True):
        pass


async def count_workers(redis: Any) -> int:
    count = 0
    async for _ in redis.scan_iter(match="worker:heartbeat:*"):
        count += 1
    return count


@router.get("/health", include_in_schema=True, summary="Check API liveness")
async def health(request: Request):
    return {"status": "ok", "version": request.app.version or "unknown", "commit": settings.GIT_COMMIT or "unknown"}


@router.get("/ready", include_in_schema=True, summary="Check API dependencies and worker readiness")
async def ready():
    checks = {"database": "ok", "redis": "ok", "migrations": "ok", "storage": "ok", "workers": 0}
    redis_client = None
    failed = False
    try:
        await check_database()
    except Exception:
        checks["database"] = "fail"
        failed = True
    try:
        redis_client = await check_redis()
        checks["workers"] = await count_workers(redis_client)
    except Exception:
        checks["redis"] = "fail"
        checks["workers"] = "fail"
        failed = True
    finally:
        if redis_client is not None:
            await redis_client.aclose()
    try:
        await check_migration()
    except Exception:
        checks["migrations"] = "fail"
        failed = True
    try:
        await check_storage()
    except Exception:
        checks["storage"] = "fail"
        failed = True
    worker_missing = checks["workers"] == 0
    if worker_missing:
        checks["workers"] = "degraded"
        if settings.READY_REQUIRE_WORKER:
            failed = True
    status = "not_ready" if failed else "ready"
    return JSONResponse(status_code=503 if failed else 200, content={"status": status, "checks": checks})
