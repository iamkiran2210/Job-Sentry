from uuid import uuid4

import pytest
from app.ai_features.models.application import Application
from app.ai_features.models.candidate import Candidate
from app.models.company import Company
from app.models.job import EmploymentType, Job, WorkMode
from app.models.job_requirement import (
    JobRequirement,
    RequirementCategory,
    RequirementImportance,
    RequirementType,
)
from app.modules.candidate_intelligence.comparison import compare_applications
from app.modules.candidate_intelligence.models import CandidateScore, ScoreEvidenceRecord
from app.modules.candidate_intelligence.schemas import CompareRequest
from app.modules.candidate_intelligence.service import ScoringService
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker


def test_comparison_request_requires_two_to_four_unique_ids():
    with pytest.raises(ValidationError):
        CompareRequest(application_ids=[uuid4()])
    with pytest.raises(ValidationError):
        CompareRequest(application_ids=[uuid4() for _ in range(5)])
    repeated = uuid4()
    with pytest.raises(ValidationError, match="unique"):
        CompareRequest(application_ids=[repeated, repeated])
    assert len(CompareRequest(application_ids=[uuid4(), uuid4()]).application_ids) == 2


@pytest.mark.parametrize("candidate_count", [2, 3, 4])
async def test_comparison_is_job_scoped_read_only_and_reports_evidence_differences(
        alembic_db, candidate_count
):
    sessions = async_sessionmaker(alembic_db, expire_on_commit=False)
    async with sessions() as session:
        company = Company(name=f"compare-{uuid4()}")
        session.add(company)
        await session.flush()
        job = Job(
            company_id=company.id,
            title="Engineer",
            description="Build services",
            employment_type=EmploymentType.FULL_TIME,
            work_mode=WorkMode.REMOTE,
        )
        session.add(job)
        await session.flush()
        requirement = JobRequirement(
            job_id=job.id,
            category=RequirementCategory.SKILLS,
            name="Python",
            requirement_type=RequirementType.MANDATORY,
            importance=RequirementImportance.HIGH,
            weight=1,
            is_mandatory=True,
        )
        session.add(requirement)
        candidates, applications, scores = [], [], []
        values = ("0.9", "0.2", "0.6", "0.8")
        for index, value in enumerate(values[:candidate_count]):
            candidate = Candidate(company_id=company.id, full_name=f"Candidate {index}")
            session.add(candidate)
            await session.flush()
            application = Application(
                company_id=company.id, job_id=job.id, candidate_id=candidate.id, status="applied"
            )
            session.add(application)
            await session.flush()
            score = CandidateScore(
                company_id=company.id,
                application_id=application.id,
                job_id=job.id,
                scoring_version="v1.4.0",
                algorithm_version="v1.4.0",
                score=75 - index,
                score_lower_bound=70,
                score_upper_bound=80,
                data_completeness=1,
                mandatory_results=[
                    {
                        "requirement_id": str(requirement.id),
                        "status": "met" if index == 0 else "not_met",
                        "evidence_ids": [f"e{index}"] if index == 0 else [],
                    }
                ],
                inputs_hash=f"{index}" * 64,
                category_detail={
                    "skills": {
                        "status": "known",
                        "match": value,
                        "weight": "1",
                        "weighted_contribution": value,
                    }
                },
                eligibility="eligible" if index == 0 else "potentially_ineligible",
                review_signals=[],
                config_snapshot={},
            )
            session.add(score)
            await session.flush()
            if index == 0:
                session.add(
                    ScoreEvidenceRecord(
                        company_id=company.id,
                        score_id=score.id,
                        application_id=application.id,
                        evidence_id=f"e{index}",
                        category="skills",
                        signal_type="exact_skill_match",
                        value=1,
                        evidence_data={"supporting_quotes": ["Python services"]},
                        matched_term="Python",
                        requirement_term="Python",
                        canonical_term="python",
                        grounded=True,
                    )
                )
            candidates.append(candidate)
            applications.append(application)
            scores.append(score)
        await session.flush()
        before = await session.scalar(select(func.count()).select_from(CandidateScore))
        result = await compare_applications(
            session, job.id, company.id, [item.id for item in applications]
        )
        assert [item["id"] for item in result["applications"]] == [
            str(item.id) for item in applications
        ]
        assert [row["result"] for row in result["skill_coverage"][0]["applications"]] == [
            "exact"
        ] + ["none"] * (candidate_count - 1)
        assert result["mandatory_coverage"][1]["counts"]["not_met"] == 1
        assert {row["type"] for row in result["differences"]} == {
            "category_spread",
            "skill_result",
            "mandatory_status",
        }
        assert result["disclaimers"]
        repeated = await compare_applications(
            session, job.id, company.id, [item.id for item in applications]
        )
        assert repeated == result
        assert await session.scalar(select(func.count()).select_from(CandidateScore)) == before

        unscored = Application(company_id=company.id, job_id=job.id, status="withdrawn")
        session.add(unscored)
        await session.flush()
        with pytest.raises(HTTPException) as error:
            await compare_applications(
                session, job.id, company.id, [applications[0].id, unscored.id]
            )
        assert error.value.status_code == 409
        assert error.value.detail["code"] == "applications_not_scored"

        other_job = Job(
            company_id=company.id,
            title="Other",
            description="Other",
            employment_type=EmploymentType.FULL_TIME,
            work_mode=WorkMode.REMOTE,
        )
        session.add(other_job)
        await session.flush()
        outside = Application(company_id=company.id, job_id=other_job.id, status="applied")
        session.add(outside)
        await session.flush()
        with pytest.raises(HTTPException) as error:
            await compare_applications(
                session, job.id, company.id, [applications[0].id, outside.id]
            )
        assert error.value.status_code == 422
        assert str(outside.id) in str(error.value.detail)

        other_company = Company(name=f"other-{uuid4()}")
        session.add(other_company)
        await session.flush()
        other_company_job = Job(
            company_id=other_company.id,
            title="Private",
            description="Private",
            employment_type=EmploymentType.FULL_TIME,
            work_mode=WorkMode.REMOTE,
        )
        session.add(other_company_job)
        await session.flush()
        foreign_app = Application(
            company_id=other_company.id, job_id=other_company_job.id, status="applied"
        )
        session.add(foreign_app)
        await session.flush()
        with pytest.raises(HTTPException) as error:
            await compare_applications(
                session, job.id, company.id, [applications[0].id, foreign_app.id]
            )
        assert error.value.status_code == 422
        assert str(foreign_app.id) in str(error.value.detail)


async def test_compare_endpoint_preserves_requested_order_and_never_scores(
        client, db_session, company_with_admin, admin_headers, monkeypatch
):
    company, _ = company_with_admin
    job = Job(
        company_id=company.id,
        title="Role",
        description="Description",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
    )
    db_session.add(job)
    await db_session.flush()
    applications = []
    for index in range(2):
        app = Application(company_id=company.id, job_id=job.id, status="applied")
        db_session.add(app)
        await db_session.flush()
        score = CandidateScore(
            company_id=company.id,
            application_id=app.id,
            job_id=job.id,
            scoring_version="v1.4.0",
            algorithm_version="v1.4.0",
            score=50 + index,
            data_completeness=1,
            mandatory_results=[],
            inputs_hash=f"{index + 2}" * 64,
            category_detail={"skills": {"status": "known", "match": 0.5, "weight": 1}},
            eligibility="eligible",
            review_signals=[],
            config_snapshot={},
        )
        db_session.add(score)
        applications.append(app)
    await db_session.flush()
    before = await db_session.scalar(select(func.count()).select_from(CandidateScore))

    async def fail(*args, **kwargs):
        raise AssertionError("compare must never score")

    monkeypatch.setattr(ScoringService, "score_application", staticmethod(fail))
    response = await client.post(
        f"/api/v1/jobs/{job.id}/compare",
        headers=admin_headers,
        json={"application_ids": [str(applications[1].id), str(applications[0].id)]},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]["applications"]] == [
        str(applications[1].id),
        str(applications[0].id),
    ]
    assert await db_session.scalar(select(func.count()).select_from(CandidateScore)) == before
