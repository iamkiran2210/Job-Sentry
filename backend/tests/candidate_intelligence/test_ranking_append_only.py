from __future__ import annotations

import uuid

import pytest
from app.ai_features.models.application import Application
from app.models.company import Company
from app.models.job import EmploymentType, Job, WorkMode
from app.models.user import User
from app.modules.candidate_intelligence.config import get_intelligence_settings
from app.modules.candidate_intelligence.models import CandidateScore, RankingHistory, RankingRun
from app.modules.candidate_intelligence.service import CandidateIntelligenceService, ScoringService
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker


async def seed_run(engine):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        company = Company(name=f"append-only-{uuid.uuid4()}")
        user = User(name="Test User", email=f"{uuid.uuid4()}@example.test", company=company)
        job = Job(
            company=company,
            title="Backend",
            description="Backend work",
            employment_type=EmploymentType.FULL_TIME,
            work_mode=WorkMode.REMOTE,
        )
        session.add_all([company, user, job])
        await session.flush()
        run_id = uuid.uuid4()
        run = RankingRun(
            run_id=run_id,
            job_id=job.id,
            status="completed",
            counts={"scored": 0, "skipped": 0, "failed": 0},
            filters_applied={},
            scoring_version="v1",
            algorithm_version="v1",
            embedding_model="stub",
            embedding_model_version="1",
            llm_model="stub",
            prompt_version="p1",
            job_requirements_hash="a" * 64,
            scoring_config_hash="b" * 64,
            triggered_by=user.id,
        )
        history = RankingHistory(
            company_id=company.id,
            job_id=job.id,
            run_id=run_id,
            application_id=None,
            candidate_score_id=None,
            rank=None,
            total_score=None,
            tie_break_key={},
            requirements_snapshot=[],
            requirements_hash="a" * 64,
            ranked_items=[],
            filters_used={},
            scoring_version="v1",
            algorithm_version="v1",
            config_snapshot={},
            config_hash="b" * 64,
            provider_snapshot={},
            embedding_model="stub",
            embedding_model_version="1",
            llm_model="stub",
            prompt_version="p1",
            job_requirements_hash="a" * 64,
            scoring_config_hash="b" * 64,
            eligibility="needs_review",
            verification_status="not_verified",
            triggered_by=user.id,
        )
        session.add_all([run, history])
        await session.commit()
        return run.id, history.id, job.id, user.id


@pytest.mark.integration
@pytest.mark.requires_pgvector
@pytest.mark.parametrize(
    ("table", "operation"),
    [
        ("ranking_run", "UPDATE"),
        ("ranking_run", "DELETE"),
        ("ranking_history", "UPDATE"),
        ("ranking_history", "DELETE"),
    ],
)
async def test_ranking_run_and_history_reject_raw_sql_mutation(alembic_db, table, operation):
    run_row_id, history_id, _, _ = await seed_run(alembic_db)
    target_id = run_row_id if table == "ranking_run" else history_id
    sessions = async_sessionmaker(alembic_db, expire_on_commit=False)
    async with sessions() as session:
        if operation == "UPDATE":
            statement = text(
                f"UPDATE job_sentry.{table} SET updated_at = updated_at WHERE id = :id"
            )
        else:
            statement = text(f"DELETE FROM job_sentry.{table} WHERE id = :id")
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(statement, {"id": target_id})
        await session.rollback()


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_job_rank_advisory_lock_returns_409_without_second_partial_run(alembic_db):
    _, _, job_id, user_id = await seed_run(alembic_db)
    sessions = async_sessionmaker(alembic_db, expire_on_commit=False)
    first, second = sessions(), sessions()
    try:
        result = await CandidateIntelligenceService.rank(
            first, job_id, user_id, {"offset": 0, "limit": 50}
        )
        assert result["run_id"]
        before_count = await second.scalar(select(func.count()).select_from(RankingRun))
        with pytest.raises(HTTPException) as caught:
            await CandidateIntelligenceService.rank(
                second, job_id, user_id, {"offset": 0, "limit": 50}
            )
        assert caught.value.status_code == 409
        assert await second.scalar(select(func.count()).select_from(RankingRun)) == before_count
        await second.rollback()
        await first.commit()
        assert await second.scalar(select(func.count()).select_from(RankingRun)) == before_count + 1
    finally:
        await first.close()
        await second.close()


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_force_rescore_reuses_current_inputs_unless_forced(alembic_db, monkeypatch):
    sessions = async_sessionmaker(alembic_db, expire_on_commit=False)
    async with sessions() as session:
        company = Company(name=f"rescore-{uuid.uuid4()}")
        job = Job(
            company=company,
            title="Backend",
            description="Backend work",
            employment_type=EmploymentType.FULL_TIME,
            work_mode=WorkMode.REMOTE,
        )
        session.add_all([company, job])
        await session.flush()
        application = Application(company_id=company.id, job_id=job.id, status="applied")
        session.add(application)
        await session.flush()
        calls = []

        async def no_external_evidence(*args):
            calls.append(1)
            return []

        monkeypatch.setattr(ScoringService, "_collect_evidence", staticmethod(no_external_evidence))
        cfg = get_intelligence_settings()
        first = await ScoringService.score_application(
            application.id, job.id, cfg, as_of=__import__("datetime").date(2026, 1, 1), db=session
        )
        reused = await ScoringService.score_application(
            application.id, job.id, cfg, as_of=__import__("datetime").date(2026, 1, 1), db=session
        )
        assert reused.id == first.id
        assert len(calls) == 1
        forced = await ScoringService.score_application(
            application.id,
            job.id,
            cfg,
            as_of=__import__("datetime").date(2026, 1, 1),
            db=session,
            force_rescore=True,
        )
        assert forced.id != first.id
        assert forced.scoring_version == first.scoring_version
        assert len(calls) == 2
        rows = (
            (
                await session.execute(
                    select(CandidateScore).where(CandidateScore.application_id == application.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
