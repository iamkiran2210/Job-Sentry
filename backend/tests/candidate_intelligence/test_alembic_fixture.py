import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_alembic_db_fixture_builds_schema_through_migrations(alembic_db: AsyncEngine):
    async with alembic_db.connect() as connection:
        version = await connection.scalar(
            text("SELECT version_num FROM job_sentry.alembic_version")
        )
        evidence_table = await connection.scalar(
            text("SELECT to_regclass('job_sentry.score_evidence') IS NOT NULL")
        )
        explanation_table = await connection.scalar(
            text("SELECT to_regclass('job_sentry.score_explanation') IS NOT NULL")
        )
        vector_extension = await connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        )
    assert version == "d7f43ae83c10"
    assert evidence_table is True
    assert explanation_table is True
    assert vector_extension is True


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_alembic_built_schema_has_no_model_drift(alembic_db: AsyncEngine):
    url = alembic_db.url.render_as_string(hide_password=False)
    env = {
        **os.environ,
        "TEST_DATABASE_URL": url,
        "ALEMBIC_TARGET": "test",
        "ALEMBIC_DATABASE_URL": url,
        "UV_OFFLINE": "1",
        "UV_NO_SYNC": "1",
    }
    result = subprocess.run(
        [str(BACKEND_ROOT / "scripts" / "alembic_test.sh"), "check"],
        cwd=BACKEND_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No new upgrade operations detected" in result.stdout + result.stderr
