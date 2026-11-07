import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_alembic_db_fixture_builds_schema_through_migrations(alembic_db: AsyncEngine):
    async with alembic_db.connect() as connection:
        version = await connection.scalar(text("SELECT version_num FROM job_sentry.alembic_version"))
        evidence_table = await connection.scalar(
            text("SELECT to_regclass('job_sentry.score_evidence') IS NOT NULL")
        )
        vector_extension = await connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        )
    assert version == "e82c4a91d307"
    assert evidence_table is True
    assert vector_extension is True
