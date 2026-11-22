import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.ai_features.models.application import Application
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.resume import Resume
from app.models.job import EmploymentType, Job, WorkMode
from app.models.job_requirement import (
    JobRequirement,
    RequirementCategory,
    RequirementImportance,
    RequirementType,
)
from app.modules.candidate_intelligence.config import get_intelligence_settings
from app.modules.candidate_intelligence.models import CandidateScore, ScoreEvidenceRecord
from app.modules.candidate_intelligence.scoring import category_formulas as formulas
from app.modules.candidate_intelligence.scoring.category_formulas import CategoryResult, aggregate
from app.modules.candidate_intelligence.service import (
    CandidateIntelligenceService,
    ScoringService,
    evidence_to_category_inputs,
)
from app.modules.candidate_intelligence.types import ScoringInputs
from sqlalchemy import select


async def seeded_application(db_session, company_with_admin):
    company, _ = company_with_admin
    job = Job(
        company_id=company.id,
        title="Backend Engineer",
        description="Python APIs",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add(
        JobRequirement(
            job_id=job.id,
            category=RequirementCategory.SKILLS,
            name="Python",
            requirement_type=RequirementType.MANDATORY,
            importance=RequirementImportance.HIGH,
            weight=1.0,
            is_mandatory=True,
        )
    )
    await db_session.flush()
    app = Application(company_id=company.id, job_id=job.id, status="applied")
    db_session.add(app)
    await db_session.flush()
    resume = Resume(
        company_id=company.id,
        job_id=job.id,
        application_id=app.id,
        original_filename="resume.pdf",
        extension="pdf",
        content_type="application/pdf",
        size_bytes=10,
        sha256=uuid.uuid4().hex,
        storage_backend="local",
        storage_key="test/resume.pdf",
    )
    db_session.add(resume)
    await db_session.flush()
    db_session.add(
        ExtractedProfile(
            resume_id=resume.id,
            company_id=company.id,
            source_text="Python backend engineer with APIs and services." * 8,
            profile_data={
                "skills": [{"name": "Python", "evidence": "Python"}],
                "employment": [],
                "projects": [],
                "education": [],
                "certifications": [],
                "contact": {},
            },
        )
    )
    await db_session.flush()
    return app, job


@pytest.mark.asyncio
async def test_score_application_persists_complete_score(
        db_session, company_with_admin, monkeypatch
):
    app, job = await seeded_application(db_session, company_with_admin)
    monkeypatch.setattr(
        "app.modules.candidate_intelligence.service.build_embedding_provider",
        lambda cfg: SimpleNamespace(
            embed_text=lambda text: SimpleNamespace(
                vector=[1.0] * cfg.embedding_dimension,
                content_hash="h",
                model_name="fake",
                model_version="1",
                dimension=cfg.embedding_dimension,
            )
        ),
    )
    monkeypatch.setattr(
        "app.modules.candidate_intelligence.service.build_llm_analyzer",
        lambda cfg: SimpleNamespace(),
    )
    await ScoringService.score_application(
        app.id, job.id, get_intelligence_settings(), as_of=date(2026, 1, 1), db=db_session
    )
    row = (
        await db_session.execute(
            select(CandidateScore).where(CandidateScore.application_id == app.id)
        )
    ).scalar_one()
    assert row.category_detail is not None and row.score is not None and row.config_snapshot
    assert (
            row.inputs_hash and row.score_lower_bound is not None and row.score_upper_bound is not None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "score_skills",
        "score_experience",
        "score_projects",
        "score_education",
        "score_certifications",
        "aggregate",
        "evaluate_mandatory",
    ],
)
async def test_persisted_score_uses_pure_scorer_sentinel(
        db_session, company_with_admin, monkeypatch, name
):
    app, job = await seeded_application(db_session, company_with_admin)
    import app.modules.candidate_intelligence.scoring.category_formulas as formulas

    category = name.removeprefix("score_")
    sentinel = object()
    if name.startswith("score_"):
        from app.modules.candidate_intelligence.scoring.category_formulas import CategoryResult

        category = "certifications" if category == "certifications" else category
        value = CategoryResult(
            category,
            "known",
            Decimal("0.1234"),
            Decimal("0.05"),
            Decimal("0.00617"),
            {"sentinel": "reached"},
        )
        monkeypatch.setattr(formulas, name, lambda *args, **kwargs: value, raising=False)
    elif name == "aggregate":
        from app.modules.candidate_intelligence.scoring.category_formulas import AggregateResult

        value = AggregateResult(
            Decimal("42.11"),
            Decimal("31.11"),
            Decimal("71.11"),
            Decimal("0.500"),
            "needs_review",
            ("sentinel_aggregate",),
        )
        monkeypatch.setattr(formulas, name, lambda *args, **kwargs: value, raising=False)
    else:
        from app.modules.candidate_intelligence.scoring.category_formulas import MandatoryEvaluation

        value = MandatoryEvaluation(
            ({"requirement_id": "sentinel", "status": "unknown", "evidence_ids": []},),
            "needs_review",
            ("sentinel_mandatory",),
        )
        monkeypatch.setattr(formulas, name, lambda *args, **kwargs: value, raising=False)
    await ScoringService.score_application(
        app.id, job.id, get_intelligence_settings(), as_of=date(2026, 1, 1), db=db_session
    )
    row = (
        await db_session.execute(
            select(CandidateScore).where(CandidateScore.application_id == app.id)
        )
    ).scalar_one()
    if name.startswith("score_"):
        assert row.category_detail[category]["match"] == "0.1234"
        assert row.category_detail[category]["components"]["sentinel"] == "reached"
    elif name == "aggregate":
        assert row.score == Decimal("42.11")
        assert row.score_lower_bound == Decimal("31.11")
        assert row.score_upper_bound == Decimal("71.11")
    else:
        assert row.mandatory_results[0]["requirement_id"] == "sentinel"


@pytest.mark.asyncio
async def test_scoring_service_does_not_call_old_analysis_path(
        db_session, company_with_admin, monkeypatch
):
    app, job = await seeded_application(db_session, company_with_admin)

    async def fail(*args, **kwargs):
        raise AssertionError("old path used")

    monkeypatch.setattr(CandidateIntelligenceService, "analyze", fail)
    await ScoringService.score_application(
        app.id, job.id, get_intelligence_settings(), as_of=date(2026, 1, 1), db=db_session
    )


@pytest.mark.asyncio
async def test_repeated_and_shuffled_inputs_are_byte_identical(
        db_session, company_with_admin, monkeypatch
):
    app, job = await seeded_application(db_session, company_with_admin)
    monkeypatch.setattr(
        "app.modules.candidate_intelligence.service.build_embedding_provider",
        lambda cfg: SimpleNamespace(
            embed_text=lambda text: SimpleNamespace(
                vector=[1.0] * cfg.embedding_dimension,
                content_hash=text,
                model_name="fake",
                model_version="1",
                dimension=cfg.embedding_dimension,
            )
        ),
    )
    monkeypatch.setattr(
        "app.modules.candidate_intelligence.service.build_llm_analyzer",
        lambda cfg: SimpleNamespace(),
    )
    first = await ScoringService.score_application(
        app.id, job.id, get_intelligence_settings(), as_of=date(2026, 1, 1), db=db_session
    )
    first_hash = first.inputs_hash
    profile = (
        await db_session.execute(
            select(ExtractedProfile)
            .join(Resume, Resume.id == ExtractedProfile.resume_id)
            .where(Resume.application_id == app.id)
        )
    ).scalar_one()
    profile.profile_data = {
        **profile.profile_data,
        "skills": [{"name": "Node.js"}, {"name": "Python"}],
    }
    await db_session.flush()
    second = await ScoringService.score_application(
        app.id, job.id, get_intelligence_settings(), as_of=date(2026, 1, 1), db=db_session
    )
    second_json = __import__("json").dumps(
        second.category_detail, sort_keys=True, separators=(",", ":")
    )
    profile.profile_data = {
        **profile.profile_data,
        "skills": list(reversed(profile.profile_data["skills"])),
    }
    await db_session.flush()
    third = await ScoringService.score_application(
        app.id, job.id, get_intelligence_settings(), as_of=date(2026, 1, 1), db=db_session
    )
    third_json = __import__("json").dumps(
        third.category_detail, sort_keys=True, separators=(",", ":")
    )
    assert second.inputs_hash == third.inputs_hash
    assert second_json == third_json
    assert first_hash != second.inputs_hash


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", ["A", "B", "C", "D"])
async def test_db_golden_score_matches_hand_values_and_pure_aggregate(
        db_session, company_with_admin, monkeypatch, fixture
):
    app, job = await seeded_application(db_session, company_with_admin)
    requirement = (
        await db_session.execute(select(JobRequirement).where(JobRequirement.job_id == job.id))
    ).scalar_one()
    requirement.is_mandatory = False
    requirement.requirement_type = RequirementType.PREFERRED
    await db_session.flush()
    cfg = get_intelligence_settings()
    values = {
        "A": {
            "skills": Decimal(".8"),
            "experience": Decimal(".5"),
            "projects": Decimal("1"),
            "education": Decimal("1"),
            "certifications": Decimal("0"),
        },
        "B": {
            "skills": Decimal(".8"),
            "experience": Decimal(".5"),
            "projects": Decimal("1"),
            "education": None,
            "certifications": None,
        },
        "C": {
            name: None
            for name in ("skills", "experience", "projects", "education", "certifications")
        },
        "D": {
            "skills": Decimal(".8"),
            "experience": Decimal(".5"),
            "projects": Decimal("1"),
            "education": Decimal("1"),
            "certifications": "not_applicable",
        },
    }[fixture]
    weights = {name: Decimal(str(getattr(cfg, f"weight_{name}"))) for name in values}
    categories = [
        CategoryResult(
            name,
            "not_applicable"
            if match == "not_applicable"
            else "unknown"
            if match is None
            else "known",
            None if match == "not_applicable" else match,
            weights[name],
            None if match is None or match == "not_applicable" else match * weights[name],
            {},
        )
        for name, match in values.items()
    ]
    import app.modules.candidate_intelligence.scoring.category_formulas as formulas

    for category, function in zip(
            values,
            (
                    "score_skills",
                    "score_experience",
                    "score_projects",
                    "score_education",
                    "score_certifications",
            ),
    ):
        item = next(result for result in categories if result.category == category)
        monkeypatch.setattr(formulas, function, lambda *args, result=item, **kwargs: result)

    async def fixed_evidence(*args):
        return []

    monkeypatch.setattr(ScoringService, "_collect_evidence", staticmethod(fixed_evidence))
    expected = aggregate(categories, [])
    persisted = await ScoringService.score_application(
        app.id, job.id, cfg, as_of=date(2026, 1, 1), db=db_session
    )
    await db_session.refresh(persisted)
    hand_values = {
        "A": (Decimal("74.50"), Decimal("1.000"), Decimal("74.50"), Decimal("74.50")),
        "B": (Decimal("75.88"), Decimal("0.850"), Decimal("64.50"), Decimal("79.50")),
        "C": (None, Decimal("0.000"), Decimal("0.00"), Decimal("100.00")),
        "D": (Decimal("78.42"), Decimal("1.000"), Decimal("78.42"), Decimal("78.42")),
    }[fixture]
    assert (
               persisted.score,
               persisted.data_completeness,
               persisted.score_lower_bound,
               persisted.score_upper_bound,
           ) == hand_values
    assert persisted.score == expected.total_score
    assert persisted.data_completeness == expected.data_completeness
    assert persisted.score_lower_bound == expected.score_lower_bound
    assert persisted.score_upper_bound == expected.score_upper_bound
    assert persisted.eligibility == expected.eligibility
    if fixture == "D":
        assert persisted.category_detail["certifications"]["status"] == "not_applicable"


@pytest.mark.asyncio
async def test_score_rederives_from_persisted_config_inputs_and_evidence(
        db_session, company_with_admin, monkeypatch
):
    app, job = await seeded_application(db_session, company_with_admin)
    monkeypatch.setattr(
        "app.modules.candidate_intelligence.service.build_embedding_provider",
        lambda cfg: SimpleNamespace(
            embed_text=lambda text: SimpleNamespace(
                vector=[1.0] * cfg.embedding_dimension,
                content_hash=text,
                model_name="fake",
                model_version="1",
                dimension=cfg.embedding_dimension,
            )
        ),
    )
    monkeypatch.setattr(
        "app.modules.candidate_intelligence.service.build_llm_analyzer",
        lambda cfg: SimpleNamespace(),
    )
    row = await ScoringService.score_application(
        app.id, job.id, get_intelligence_settings(), as_of=date(2026, 1, 1), db=db_session
    )
    snapshot = row.config_snapshot
    stored = snapshot["reproducibility_inputs"]
    inputs = ScoringInputs(
        tuple(stored["skills"]),
        tuple(stored["experience"]),
        tuple(stored["projects"]),
        tuple(stored["education"]),
        tuple(stored["certifications"]),
        tuple(stored["requirements"]),
        date.fromisoformat(stored["as_of"]),
    )
    records = (
        (
            await db_session.execute(
                select(ScoreEvidenceRecord).where(ScoreEvidenceRecord.score_id == row.id)
            )
        )
        .scalars()
        .all()
    )
    evidence = [SimpleNamespace(**record.evidence_data) for record in records]
    adapted = evidence_to_category_inputs(evidence, inputs)
    reqs = list(inputs.requirements)
    normalize = lambda value: {
        "certification": "certifications",
        "project": "projects",
        "responsibility": "projects",
    }.get(value, value)
    category = lambda item: normalize(item["category"])
    weights = {
        name: Decimal(snapshot["weights"][name])
        for name in ("skills", "experience", "projects", "education", "certifications")
    }
    skill = formulas.score_skills(
        [r for r in reqs if category(r) == "skills"], adapted["skill_credits"], weights["skills"]
    )
    experience_reqs = [r for r in reqs if category(r) == "experience"]
    required_years = (
        Decimal(experience_reqs[0]["name"].split()[0])
        if experience_reqs and experience_reqs[0]["name"].split()[0].isdigit()
        else None
    )
    experience = formulas.score_experience(
        list(inputs.experience),
        adapted["experience_relevance"],
        required_years,
        inputs.as_of,
        weights["experience"],
    )
    projects = formulas.score_projects(
        list(inputs.projects), adapted["project_relevance"], weights["projects"]
    )
    education_reqs = [r for r in reqs if category(r) == "education"]
    levels = {
        "none": 0,
        "high_school": 1,
        "high school": 1,
        "associate": 2,
        "bachelor": 3,
        "b.tech": 3,
        "be": 3,
        "bsc": 3,
        "ba": 3,
        "master": 4,
        "m.tech": 4,
        "ms": 4,
        "msc": 4,
        "mba": 4,
        "doctorate": 5,
        "phd": 5,
    }
    education = formulas.score_education(
        [str(x.get("degree", "")) for x in inputs.education if x.get("degree")],
        education_reqs[0]["name"] if education_reqs else None,
        levels,
        weights["education"],
    )
    certifications = formulas.score_certifications(
        [r for r in reqs if category(r) == "certifications"],
        list(inputs.certifications),
        snapshot["skill_aliases"],
        weights["certifications"],
        inputs.as_of,
    )
    mandatory = formulas.evaluate_mandatory(reqs, evidence)
    reproduced = formulas.aggregate(
        [skill, experience, projects, education, certifications], list(mandatory.results)
    )
    assert reproduced.total_score == row.score
    assert reproduced.score_lower_bound == row.score_lower_bound
    assert reproduced.score_upper_bound == row.score_upper_bound
    assert reproduced.data_completeness == row.data_completeness
    assert reproduced.eligibility == row.eligibility
