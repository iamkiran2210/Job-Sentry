from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.candidate_intelligence.scoring.category_formulas import (
    CategoryResult,
    aggregate,
    certifications_result,
    education_result,
    experience_result,
    projects_result,
    score_skills,
    evaluate_mandatory,
)
from app.modules.candidate_intelligence.types import ScoreEvidence
from app.modules.candidate_intelligence.evidence.providers import DeterministicMockEmbeddingProvider
from app.modules.candidate_intelligence.config import get_intelligence_settings
from app.modules.candidate_intelligence.service import ScoringService, build_scoring_inputs

WEIGHTS = {
    "skills": Decimal("0.40"),
    "experience": Decimal("0.25"),
    "projects": Decimal("0.20"),
    "education": Decimal("0.10"),
    "certifications": Decimal("0.05"),
}


def test_fixture_c_all_unknown_has_no_score_and_review():
    categories = [
        CategoryResult(name, "unknown", None, weight, None, {}) for name, weight in WEIGHTS.items()
    ]
    result = aggregate(categories, [])
    assert result.total_score is None
    assert result.eligibility == "needs_review"
    assert result.score_lower_bound == Decimal("0.00")
    assert result.score_upper_bound == Decimal("100.00")
    assert result.data_completeness == Decimal("0.000")


def test_fixture_d_not_applicable_is_excluded_from_completeness_denominator():
    categories = [
        CategoryResult("skills", "known", Decimal("0.8"), WEIGHTS["skills"], Decimal("0.32"), {}),
        CategoryResult("experience", "unknown", None, WEIGHTS["experience"], None, {}),
        CategoryResult("projects", "unknown", None, WEIGHTS["projects"], None, {}),
        CategoryResult("education", "unknown", None, WEIGHTS["education"], None, {}),
        CategoryResult(
            "certifications", "not_applicable", None, WEIGHTS["certifications"], None, {}
        ),
    ]
    result = aggregate(categories, [])
    assert result.total_score == Decimal("80.00")
    assert result.data_completeness == Decimal("0.421")
    assert result.score_lower_bound == Decimal("33.68")
    assert result.score_upper_bound == Decimal("91.58")


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("doctorate", "1.0000"),
        ("bachelor", "1.0000"),
        ("associate", "0.5000"),
        ("high_school", "0.0000"),
    ],
)
def test_fixture_f_education_gap_rules(candidate, expected):
    levels = {
        "none": 0,
        "high_school": 1,
        "associate": 2,
        "bachelor": 3,
        "master": 4,
        "doctorate": 5,
    }
    assert education_result([candidate], "bachelor", levels, Decimal("0.1")).match == Decimal(
        expected
    )


def test_fixture_f_unrecognized_and_missing_education_are_unknown():
    levels = {
        "none": 0,
        "high_school": 1,
        "associate": 2,
        "bachelor": 3,
        "master": 4,
        "doctorate": 5,
    }
    assert (
            education_result(["mystery credential"], "bachelor", levels, Decimal("0.1")).status
            == "unknown"
    )
    assert education_result([], "bachelor", levels, Decimal("0.1")).status == "unknown"
    assert education_result(["B.Tech"], "master", levels, Decimal("0.1")).match == Decimal("0.5000")


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, None), (1, Decimal("0.2000")), (2, Decimal("0.5000")), (5, Decimal("0.6667"))],
)
def test_fixture_g_projects_take_top_three_and_tie_break_by_id(count, expected):
    projects = [{"id": chr(97 + i)} for i in range(count)]
    values = {
        "a": Decimal("0.2"),
        "b": Decimal("0.8"),
        "c": Decimal("0.8"),
        "d": Decimal("0.1"),
        "e": Decimal("0.4"),
    }
    result = projects_result(list(reversed(projects)), values, Decimal("0.2"), 3)
    if expected is None:
        assert result.status == "unknown"
    else:
        assert result.match == expected
    if count == 5:
        assert result.components["ids_used"] == ["b", "c", "e"]
        assert "fewer_than_n_projects" not in result.notes


def test_fixture_h_certifications_absent_partial_expired_and_unknown_expiry():
    reqs = [{"id": "aws", "name": "AWS Certified", "is_mandatory": False}]
    assert (
            certifications_result([], [], {}, Decimal("0.05"), date(2026, 1, 1)).status
            == "not_applicable"
    )
    assert (
            certifications_result(reqs, [], {}, Decimal("0.05"), date(2026, 1, 1)).status == "unknown"
    )
    partial = certifications_result(
        reqs + [{"id": "gcp", "name": "GCP"}],
        [{"name": "AWS Certified"}],
        {},
        Decimal("0.05"),
        date(2026, 1, 1),
    )
    assert partial.match == Decimal("0.5000")
    expired = certifications_result(
        reqs,
        [{"name": "AWS Certified", "expiry_date": "2025-01"}],
        {},
        Decimal("0.05"),
        date(2026, 1, 1),
    )
    assert expired.match == Decimal("0.0000") and "cert_expired" in expired.notes
    unknown_expiry = certifications_result(
        reqs, [{"name": "AWS Certified"}], {}, Decimal("0.05"), date(2026, 1, 1)
    )
    assert (
            unknown_expiry.match == Decimal("1.0000") and "cert_expiry_unknown" in unknown_expiry.notes
    )


def test_fixture_i_rounding_is_half_up_at_output_edge():
    category = score_skills(
        [{"id": "x", "name": "skill"}], {"x": (Decimal("0.12345"), "evidence-1")}, Decimal("1")
    )
    result = aggregate(
        [CategoryResult("skills", "known", category.match, Decimal("1"), category.match, {})], []
    )
    assert category.match == Decimal("0.1235")
    assert result.total_score == Decimal("12.35")


def test_skill_requirement_weights_and_unknown_semantic_credits():
    requirements = [
        {"id": "mandatory", "name": "Python", "is_mandatory": True},
        {"id": "preferred", "name": "SQL", "is_mandatory": False},
    ]
    result = score_skills(
        requirements,
        {"mandatory": (Decimal("0.6"), "e1"), "preferred": (Decimal("1"), "e2")},
        Decimal("0.4"),
    )
    assert result.match == Decimal("0.7333")
    assert result.evidence_ids == ("e1", "e2")
    assert score_skills([], {}, Decimal("0.4")).status == "not_applicable"
    assert score_skills(requirements, {}, Decimal("0.4")).status == "unknown"
    assert score_skills(
        requirements,
        {"mandatory": (Decimal("4"), "e1"), "preferred": (Decimal("-1"), "e2")},
        Decimal("0.4"),
    ).match == Decimal("0.6667")


def test_experience_no_entries_is_unknown_and_fixed_as_of_merges_overlaps():
    as_of = date(2026, 1, 1)
    assert experience_result([], {}, Decimal("5"), as_of, Decimal("0.25")).status == "unknown"
    entries = [
        {"id": "a", "start_date": "2020-01", "end_date": "2022-12"},
        {"id": "b", "start_date": "2022-01", "is_current": True},
    ]
    result = experience_result(
        entries, {"a": Decimal("0.8"), "b": Decimal("0.6")}, Decimal("5"), as_of, Decimal("0.25")
    )
    assert result.components["relevant_years"] == Decimal(73) / Decimal(12)


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        (
                [
                    ScoreEvidence(
                        "exact-1", "skills", "exact_skill_match", 1.0, requirement_term="Python"
                    )
                ],
                "met",
        ),
        (
                [
                    ScoreEvidence(
                        "miss-1", "skills", "semantic_similarity", 0.6, requirement_term="Python"
                    )
                ],
                "not_met",
        ),
        (
                [ScoreEvidence("llm-1", "projects", "llm_relevance", 1.0, requirement_term="Python")],
                "unknown",
        ),
        ([], "unknown"),
    ],
)
def test_mandatory_only_exact_alias_or_rule_can_be_met(evidence, expected):
    requirement = [{"id": "r1", "name": "Python", "category": "skills", "is_mandatory": True}]
    result = evaluate_mandatory(requirement, evidence)
    assert result.results[0]["status"] == expected
    assert result.eligibility == (
        "eligible"
        if expected == "met"
        else "potentially_ineligible"
        if expected == "not_met"
        else "needs_review"
    )


def test_no_mandatory_requirements_is_eligible():
    assert evaluate_mandatory([], []).eligibility == "eligible"


@pytest.mark.asyncio
async def test_protected_profile_fields_are_excluded_from_llm_prompt(monkeypatch):
    captured = {}

    class Analyzer:
        async def analyze_relevance(self, requirement_text, claim_text, full_resume_text):
            captured["text"] = full_resume_text
            return SimpleNamespace(
                rating="high",
                rationale="Grounded",
                supporting_quotes=["Built APIs"],
                model_name="test",
                model_version="1",
            )

    profile = {
        "employment": [
            {
                "id": "e1",
                "title": "Backend engineer",
                "description": "Built APIs",
                "gender": "private",
                "age": 37,
                "nationality": "private",
                "address": "private",
            }
        ]
    }
    requirements = [
        SimpleNamespace(
            id="r1",
            category="experience",
            name="backend systems",
            requirement_type="preferred",
            is_mandatory=False,
        )
    ]
    inputs = build_scoring_inputs(None, None, date(2026, 1, 1), profile, requirements)
    monkeypatch.setattr(
        "app.modules.candidate_intelligence.service.build_embedding_provider",
        lambda cfg: DeterministicMockEmbeddingProvider(8),
    )
    monkeypatch.setattr(
        "app.modules.candidate_intelligence.service.build_llm_analyzer", lambda cfg: Analyzer()
    )
    await ScoringService._collect_evidence(inputs, get_intelligence_settings())
    assert "Built APIs" in captured["text"]
    for protected in ("private", "gender", "nationality", "address", "37"):
        assert protected not in captured["text"]
