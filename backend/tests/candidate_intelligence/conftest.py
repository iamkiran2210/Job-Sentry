"""Alembic-backed PostgreSQL fixtures for schema-sensitive Phase 4 tests."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import asyncpg
import pytest_asyncio
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


ALEMBIC_DATABASE = "job_sentry_phase4_alembic_test"
BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_TEST_SCRIPT = BACKEND_ROOT / "scripts" / "alembic_test.sh"


def _asyncpg_args(url, database: str | None = None) -> dict:
    if "test" not in (database or url.database or "").casefold():
        raise RuntimeError("Alembic fixture refuses a database name without 'test'")
    return {
        "user": url.username,
        "password": url.password,
        "host": url.host or "localhost",
        "port": url.port or 5432,
        "database": database or url.database,
        "timeout": 5,
        "command_timeout": 30,
    }


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def alembic_db() -> AsyncEngine:
    """Create a disposable database, migrate it through the guarded wrapper, and yield its engine."""
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not raw_url:
        raise RuntimeError("alembic_db requires TEST_DATABASE_URL for a disposable test database")
    admin_url = make_url(raw_url)
    if "test" not in (admin_url.database or "").casefold():
        raise RuntimeError("alembic_db requires TEST_DATABASE_URL to name a test database")
    if admin_url.database == ALEMBIC_DATABASE:
        raise RuntimeError("TEST_DATABASE_URL must be a separate admin test database")

    admin = await asyncpg.connect(**_asyncpg_args(admin_url))
    engine = None
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{ALEMBIC_DATABASE}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{ALEMBIC_DATABASE}" TEMPLATE template0')
        target_url = admin_url.set(database=ALEMBIC_DATABASE).render_as_string(hide_password=False)
        target_conn = await asyncpg.connect(**_asyncpg_args(admin_url, ALEMBIC_DATABASE))
        try:
            await target_conn.execute("CREATE SCHEMA job_sentry")
            await target_conn.execute("CREATE EXTENSION vector WITH SCHEMA public")
        finally:
            await target_conn.close()

        env = {
            **os.environ,
            "TEST_DATABASE_URL": target_url,
            "ALEMBIC_TARGET": "test",
            "ALEMBIC_DATABASE_URL": target_url,
            "UV_OFFLINE": "1",
            "UV_NO_SYNC": "1",
        }
        result = subprocess.run(
            [str(ALEMBIC_TEST_SCRIPT), "upgrade", "head"],
            cwd=BACKEND_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode:
            raise RuntimeError(
                "Guarded Alembic upgrade failed for the disposable alembic_db; "
                f"exit={result.returncode}. Output was captured and omitted to avoid exposing connection data."
            )

        engine = create_async_engine(
            target_url,
            connect_args={"server_settings": {"search_path": "job_sentry,public"}},
        )
        yield engine
    finally:
        if engine is not None:
            await engine.dispose()
        await admin.execute(f'DROP DATABASE IF EXISTS "{ALEMBIC_DATABASE}" WITH (FORCE)')
        await admin.close()
