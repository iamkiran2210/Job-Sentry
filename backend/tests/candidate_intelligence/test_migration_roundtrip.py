"""Real PostgreSQL migration, legacy-data, downgrade, and schema round-trip test."""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy.engine import URL, make_url


pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_SCRIPT = BACKEND_ROOT / "scripts" / "alembic_test.sh"
ROUNDTRIP_DATABASE = "job_sentry_roundtrip_test"
BASELINE_REVISION = "b7d2e9a4c1f5"
PHASE4_INITIAL_REVISION = "c4e91a72b603"
PHASE4_PRE_TYPED_REVISION = "d6f3a810bc42"
PHASE4_HEAD = "d7f43ae83c10"


def _connection_args(url: URL, database: str | None = None) -> dict:
    if "test" not in (database or url.database or "").casefold():
        raise AssertionError("Migration integration test refuses non-test database names")
    return {
        "user": url.username,
        "password": url.password,
        "host": url.host or "localhost",
        "port": url.port or 5432,
        "database": database or url.database,
        "timeout": 5,
        "command_timeout": 30,
    }


def _roundtrip_url(base_url: str) -> str:
    parsed = make_url(base_url)
    return parsed.set(database=ROUNDTRIP_DATABASE).render_as_string(hide_password=False)


def _safe_output(output: str, database_url: str) -> str:
    masked_url = make_url(database_url).render_as_string(hide_password=True)
    output = output.replace(database_url, masked_url)
    return re.sub(r"(postgres(?:ql)?(?:\+\w+)?://[^:/\s]+:)[^@/\s]*@", r"\1***@", output)


def _run_alembic(database_url: str, *args: str) -> str:
    env = {
        **os.environ,
        "TEST_DATABASE_URL": database_url,
        "ALEMBIC_TARGET": "test",
        "ALEMBIC_DATABASE_URL": database_url,
    }
    command = [str(MIGRATION_SCRIPT), *args]
    result = subprocess.run(command, cwd=BACKEND_ROOT, env=env, text=True, capture_output=True, timeout=60)
    output = result.stdout + result.stderr
    assert result.returncode == 0, _safe_output(output, database_url)
    return output


async def _snapshot_schema(conn: asyncpg.Connection) -> dict:
    tables = await conn.fetch(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'job_sentry' AND table_type = 'BASE TABLE' ORDER BY table_name"
    )
    columns = await conn.fetch(
        "SELECT table_name, column_name, data_type, udt_name, is_nullable, column_default "
        "FROM information_schema.columns WHERE table_schema = 'job_sentry' "
        "ORDER BY table_name, ordinal_position"
    )
    indexes = await conn.fetch(
        "SELECT tablename, indexname, indexdef FROM pg_indexes "
        "WHERE schemaname = 'job_sentry' ORDER BY tablename, indexname"
    )
    constraints = await conn.fetch(
        "SELECT c.conrelid::regclass::text AS table_name, c.conname, c.contype, "
        "pg_get_constraintdef(c.oid) AS definition FROM pg_constraint c "
        "JOIN pg_namespace n ON n.oid = c.connamespace "
        "WHERE n.nspname = 'job_sentry' ORDER BY table_name, c.conname"
    )
    enums = await conn.fetch(
        "SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder) AS labels "
        "FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
        "JOIN pg_namespace n ON n.oid = t.typnamespace "
        "WHERE n.nspname = 'job_sentry' GROUP BY t.typname ORDER BY t.typname"
    )
    triggers = await conn.fetch(
        "SELECT c.relname AS table_name, t.tgname, pg_get_triggerdef(t.oid) AS definition "
        "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'job_sentry' AND NOT t.tgisinternal "
        "ORDER BY table_name, t.tgname"
    )
    extension = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
    return {
        "tables": [tuple(row) for row in tables],
        "columns": [tuple(row) for row in columns],
        "indexes": [tuple(row) for row in indexes],
        "constraints": [tuple(row) for row in constraints],
        "enums": [tuple(row) for row in enums],
        "triggers": [tuple(row) for row in triggers],
        "vector_extension": extension,
    }


async def _seed_phase1_to_3_rows(conn: asyncpg.Connection) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    company_id, user_id, job_id, candidate_id, application_id = (uuid4() for _ in range(5))
    await conn.execute(
        "INSERT INTO job_sentry.companies (id, name, created_at, updated_at) VALUES ($1, $2, $3, $3)",
        company_id, "Migration Fixture Co", now,
    )
    await conn.execute(
        "INSERT INTO job_sentry.users (id, name, email, role, company_id, auth_provider, is_active, is_verified, created_at, updated_at) "
        "VALUES ($1, $2, $3, 'ADMIN', $4, 'EMAIL', true, true, $5, $5)",
        user_id, "Migration Fixture Admin", f"migration-{user_id}@example.test", company_id, now,
    )
    await conn.execute(
        "INSERT INTO job_sentry.jobs (id, company_id, title, description, employment_type, work_mode, openings, status, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, 'full_time', 'remote', 1, 'draft', $5, $5)",
        job_id, company_id, "Migration Fixture Role", "Phase 1-3 row preservation", now,
    )
    await conn.execute(
        "INSERT INTO job_sentry.candidates (id, company_id, full_name, email, normalized_email, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $4, $5, $5)",
        candidate_id, company_id, "Legacy Candidate", f"candidate-{candidate_id}@example.test", now,
    )
    await conn.execute(
        "INSERT INTO job_sentry.applications (id, company_id, job_id, candidate_id, status, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, 'completed', $5, $5)",
        application_id, company_id, job_id, candidate_id, now,
    )
    return {"company_id": str(company_id), "user_id": str(user_id), "job_id": str(job_id),
            "candidate_id": str(candidate_id), "application_id": str(application_id)}


@pytest.mark.asyncio
async def test_postgres_migration_roundtrip_and_phase1_to_3_data_survival():
    raw_test_url = os.environ.get("TEST_DATABASE_URL")
    assert raw_test_url, "Set TEST_DATABASE_URL to the disposable job_sentry_test database"
    base = make_url(raw_test_url)
    assert "test" in (base.database or "").casefold(), "TEST_DATABASE_URL must name a test database"
    roundtrip_url = _roundtrip_url(raw_test_url)

    admin = await asyncpg.connect(**_connection_args(base))
    roundtrip_conn = None
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{ROUNDTRIP_DATABASE}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{ROUNDTRIP_DATABASE}" TEMPLATE template0')
        roundtrip_conn = await asyncpg.connect(**_connection_args(base, ROUNDTRIP_DATABASE))
        await roundtrip_conn.execute("CREATE SCHEMA job_sentry")
        await roundtrip_conn.execute("CREATE EXTENSION vector WITH SCHEMA public")
        await roundtrip_conn.close()
        roundtrip_conn = None

        heads = _run_alembic(roundtrip_url, "heads")
        head_rows = [line.strip() for line in heads.splitlines() if "(head)" in line]
        assert head_rows == [f"{PHASE4_HEAD} (head)"], _safe_output(heads, roundtrip_url)

        # Build Phase 1-3 only through Alembic, then retain representative legacy rows.
        _run_alembic(roundtrip_url, "upgrade", BASELINE_REVISION)
        roundtrip_conn = await asyncpg.connect(**_connection_args(base, ROUNDTRIP_DATABASE))
        legacy = await _seed_phase1_to_3_rows(roundtrip_conn)
        unknown_application_id = uuid4()
        await roundtrip_conn.execute(
            "INSERT INTO job_sentry.applications "
            "(id, company_id, job_id, candidate_id, status, created_at, updated_at) "
            "VALUES ($1, $2, $3, NULL, 'unknown_legacy', $4, $4)",
                unknown_application_id, UUID(legacy["company_id"]),
                UUID(legacy["job_id"]), datetime.now(timezone.utc),
        )
        legacy["unknown_application_id"] = str(unknown_application_id)
        await roundtrip_conn.close()
        roundtrip_conn = None

        _run_alembic(roundtrip_url, "upgrade", PHASE4_INITIAL_REVISION)
        roundtrip_conn = await asyncpg.connect(**_connection_args(base, ROUNDTRIP_DATABASE))
        now = datetime.now(timezone.utc)
        score_id, verification_id, evidence_id, history_id = (uuid4() for _ in range(4))
        company_id = uuid4()
        # The score/evidence rows use the already seeded company/application/job.
        await roundtrip_conn.execute(
            "INSERT INTO job_sentry.candidate_scores "
            "(id, company_id, application_id, scoring_version, algorithm_version, category_detail, eligibility, review_signals, config_snapshot, created_at, updated_at) "
            "VALUES ($1, $2, $3, 'legacy-v1', 'legacy-v1', '{}'::jsonb, 'needs_review', '[]'::jsonb, '{}'::jsonb, $4, $4)",
            score_id, legacy["company_id"], legacy["application_id"], now,
        )
        await roundtrip_conn.execute(
            "INSERT INTO job_sentry.verification_results "
            "(id, company_id, application_id, check_type, status, signal, details, created_at, updated_at) "
            "VALUES ($1, $2, $3, 'email_syntax', 'passed', 'legacy row', '{}'::jsonb, $4, $4)",
            verification_id, legacy["company_id"], legacy["application_id"], now,
        )
        await roundtrip_conn.execute(
            "INSERT INTO job_sentry.score_evidence "
            "(id, company_id, score_id, application_id, evidence_id, category, signal_type, value, evidence_data, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, 'legacy-evidence', 'skills', 'exact_skill_match', 1, '{}'::jsonb, $5, $5)",
            evidence_id, legacy["company_id"], score_id, legacy["application_id"], now,
        )
        await roundtrip_conn.execute(
            "INSERT INTO job_sentry.ranking_history "
            "(id, company_id, job_id, requirements_snapshot, requirements_hash, ranked_items, filters_used, scoring_version, algorithm_version, config_snapshot, triggered_by, created_at, updated_at) "
            "VALUES ($1, $2, $3, '[]'::jsonb, $4, '[]'::jsonb, '{}'::jsonb, 'legacy-v1', 'legacy-v1', '{}'::jsonb, $5, $6, $6)",
            history_id, legacy["company_id"], legacy["job_id"], "0" * 64, legacy["user_id"], now,
        )
        await roundtrip_conn.close()
        roundtrip_conn = None

        _run_alembic(roundtrip_url, "upgrade", "head")
        roundtrip_conn = await asyncpg.connect(**_connection_args(base, ROUNDTRIP_DATABASE))
        assert await roundtrip_conn.fetchval("SELECT count(*) FROM job_sentry.companies WHERE id = $1", legacy["company_id"]) == 1
        assert await roundtrip_conn.fetchval("SELECT count(*) FROM job_sentry.jobs WHERE id = $1", legacy["job_id"]) == 1
        assert await roundtrip_conn.fetchval("SELECT count(*) FROM job_sentry.candidates WHERE id = $1", legacy["candidate_id"]) == 1
        assert await roundtrip_conn.fetchval("SELECT count(*) FROM job_sentry.applications WHERE id = $1", legacy["application_id"]) == 1
        assert await roundtrip_conn.fetchval("SELECT status FROM job_sentry.applications WHERE id = $1", legacy["application_id"]) == "analyzed"
        assert await roundtrip_conn.fetchval("SELECT status FROM job_sentry.applications WHERE id = $1", unknown_application_id) == "applied"
        assert await roundtrip_conn.fetchval("SELECT job_id FROM job_sentry.candidate_scores WHERE id = $1", score_id) == __import__("uuid").UUID(legacy["job_id"])
        assert json.loads(await roundtrip_conn.fetchval(
            "SELECT mandatory_results FROM job_sentry.candidate_scores WHERE id = $1", score_id
        )) == []
        assert await roundtrip_conn.fetchval("SELECT checker_version FROM job_sentry.verification_results WHERE id = $1", verification_id) == "v1"
        assert await roundtrip_conn.fetchval("SELECT is_proof FROM job_sentry.score_evidence WHERE id = $1", evidence_id) is False
        assert await roundtrip_conn.fetchval("SELECT run_id FROM job_sentry.ranking_history WHERE id = $1", history_id) == history_id
        assert await roundtrip_conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')") is True
        schema_before = await _snapshot_schema(roundtrip_conn)
        await roundtrip_conn.close()
        roundtrip_conn = None

        drift = _run_alembic(roundtrip_url, "check")
        assert "No new upgrade operations detected." in drift
        _run_alembic(roundtrip_url, "downgrade", PHASE4_PRE_TYPED_REVISION)
        roundtrip_conn = await asyncpg.connect(**_connection_args(base, ROUNDTRIP_DATABASE))
        assert await roundtrip_conn.fetchval("SELECT status FROM job_sentry.applications WHERE id = $1", legacy["application_id"]) == "completed"
        assert await roundtrip_conn.fetchval("SELECT status FROM job_sentry.applications WHERE id = $1", unknown_application_id) == "unknown_legacy"
        assert await roundtrip_conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')") is True
        await roundtrip_conn.close()
        roundtrip_conn = None
        _run_alembic(roundtrip_url, "upgrade", "head")

        roundtrip_conn = await asyncpg.connect(**_connection_args(base, ROUNDTRIP_DATABASE))
        schema_after = await _snapshot_schema(roundtrip_conn)
        assert schema_after == schema_before
        assert schema_after["vector_extension"] is True
        assert await roundtrip_conn.fetchval("SELECT count(*) FROM job_sentry.applications WHERE id = $1", legacy["application_id"]) == 1
        assert await roundtrip_conn.fetchval("SELECT status FROM job_sentry.applications WHERE id = $1", legacy["application_id"]) == "analyzed"
        assert await roundtrip_conn.fetchval("SELECT status FROM job_sentry.applications WHERE id = $1", unknown_application_id) == "applied"
    finally:
        if roundtrip_conn is not None and not roundtrip_conn.is_closed():
            await roundtrip_conn.close()
        await admin.execute(f'DROP DATABASE IF EXISTS "{ROUNDTRIP_DATABASE}" WITH (FORCE)')
        await admin.close()
