from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.ai_features.models.application import Application
from app.models.job import EmploymentType, Job, WorkMode
from app.modules.candidate_intelligence.models import RankingHistory
from app.modules.candidate_intelligence.ranking.service import rank_rows
from app.modules.candidate_intelligence.service import CandidateIntelligenceService, ScoringService


def row(app_id, **values):
    result = {
        "application_id": str(app_id), "application_created_at": "2026-01-01T00:00:00+00:00",
        "score": 80.0, "eligibility": "eligible", "skills_score": 0.8,
        "data_completeness": 0.8, "status": "applied", "verification_statuses": [],
    }
    result.update(values)
    return result


def order(left, right):
    return [item["application_id"] for item in rank_rows([left, right])]


def test_rank_tiebreak_step_1_total_descending_and_null_last():
    assert order(row("lower", score=79), row("higher", score=80)) == ["higher", "lower"]
    assert order(row("null", score=None), row("zero", score=0)) == ["zero", "null"]


def test_rank_tiebreak_step_2_eligibility_priority():
    assert order(row("potential", eligibility="potentially_ineligible"), row("review", eligibility="needs_review")) == ["review", "potential"]
    assert order(row("review", eligibility="needs_review"), row("eligible", eligibility="eligible")) == ["eligible", "review"]


def test_rank_tiebreak_step_3_skills_match_descending():
    assert order(row("lower", skills_score=0.7), row("higher", skills_score=0.8)) == ["higher", "lower"]


def test_rank_tiebreak_step_4_completeness_descending():
    assert order(row("lower", data_completeness=0.6), row("higher", data_completeness=0.9)) == ["higher", "lower"]


def test_rank_tiebreak_step_5_created_at_ascending():
    assert order(row("later", application_created_at="2026-01-02T00:00:00+00:00"), row("earlier", application_created_at="2026-01-01T00:00:00+00:00")) == ["earlier", "later"]


def test_rank_tiebreak_step_6_application_id_ascending():
    assert order(row("b"), row("a")) == ["a", "b"]


def test_rank_is_deterministic_for_shuffled_input_and_one_based_without_gaps():
    rows = [row(str(i), score=float(i % 3), skills_score=float(i % 2)) for i in range(12)]
    forward = rank_rows(copy.deepcopy(rows))
    reverse = rank_rows(copy.deepcopy(list(reversed(rows))))
    assert [(x["application_id"], x["rank"]) for x in forward] == [(x["application_id"], x["rank"]) for x in reverse]
    assert [x["rank"] for x in forward] == list(range(1, 13))


def test_ranking_filters_before_pagination_and_keeps_global_filtered_ranks():
    rows = [row(str(i), score=float(i), eligibility="eligible" if i < 24 and i % 2 == 0 else "needs_review") for i in range(25)]
    first = rank_rows(copy.deepcopy(rows), offset=0, limit=10, eligibility="eligible")
    second = rank_rows(copy.deepcopy(rows), offset=10, limit=10, eligibility="eligible")
    assert len(first) == 10 and len(second) == 2
    assert [x["rank"] for x in first] == list(range(1, 11))
    assert [x["rank"] for x in second] == [11, 12]
    assert len(first) + len(second) == 12
    assert {x["application_id"] for x in first}.isdisjoint({x["application_id"] for x in second})


@pytest.mark.asyncio
async def test_rank_runs_persist_provenance_are_repeatable_and_job_scoped(db_session, company_with_admin, monkeypatch):
    company, user = company_with_admin
    job = Job(company_id=company.id, title="Backend", description="Backend systems", employment_type=EmploymentType.FULL_TIME, work_mode=WorkMode.REMOTE)
    other_job = Job(company_id=company.id, title="Other", description="Other role", employment_type=EmploymentType.FULL_TIME, work_mode=WorkMode.REMOTE)
    db_session.add_all([job, other_job])
    await db_session.flush()
    target_apps = [Application(company_id=company.id, job_id=job.id, status="applied") for _ in range(2)]
    other_app = Application(company_id=company.id, job_id=other_job.id, status="applied")
    db_session.add_all([*target_apps, other_app])
    await db_session.flush()

    original_score_application = ScoringService.score_application
    calls = []
    async def count_score(*args, **kwargs):
        calls.append(args[0])
        return await original_score_application(*args, **kwargs)
    monkeypatch.setattr(ScoringService, "score_application", staticmethod(count_score))

    first = await CandidateIntelligenceService.rank(db_session, job.id, user.id, {"offset": 0, "limit": 50})
    assert len(calls) == 2
    first_rows = (await db_session.execute(select(RankingHistory).where(RankingHistory.run_id == uuid.UUID(first["run_id"])).order_by(RankingHistory.rank))).scalars().all()
    assert len(first_rows) == 2
    assert all(item.application_id in {app.id for app in target_apps} for item in first_rows)
    assert all(item.job_id == job.id and item.triggered_by == user.id for item in first_rows)
    assert all(item.tie_break_key and item.scoring_version and item.algorithm_version and item.config_hash and item.requirements_hash for item in first_rows)
    assert all(item.provider_snapshot.get("embedding_model") and item.provider_snapshot.get("embedding_version") and item.provider_snapshot.get("llm_model") and item.provider_snapshot.get("llm_prompt_version") for item in first_rows)
    assert all(item.ranked_items and all("eligibility" in ranked and "verification_statuses" in ranked for ranked in item.ranked_items) for item in first_rows)
    before = [(item.id, item.run_id, item.application_id, item.rank, item.total_score, copy.deepcopy(item.tie_break_key), copy.deepcopy(item.ranked_items), item.config_hash, copy.deepcopy(item.provider_snapshot)) for item in first_rows]

    second = await CandidateIntelligenceService.rank(db_session, job.id, user.id, {"offset": 0, "limit": 50})
    assert second["run_id"] != first["run_id"]
    old_rows_after = (await db_session.execute(select(RankingHistory).where(RankingHistory.run_id == uuid.UUID(first["run_id"])).order_by(RankingHistory.rank))).scalars().all()
    after = [(item.id, item.run_id, item.application_id, item.rank, item.total_score, item.tie_break_key, item.ranked_items, item.config_hash, item.provider_snapshot) for item in old_rows_after]
    assert after == before
    newest = (await db_session.execute(select(RankingHistory).where(RankingHistory.run_id == uuid.UUID(second["run_id"])))).scalars().all()
    assert len(newest) == 2
