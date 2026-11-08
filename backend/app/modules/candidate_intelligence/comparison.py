"""Read-only, job-scoped comparison assembled from persisted score evidence."""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_features.models.application import Application
from app.ai_features.models.candidate import Candidate
from app.models.job_requirement import JobRequirement
from app.modules.candidate_intelligence.config import get_intelligence_settings
from app.modules.candidate_intelligence.models import (
    CandidateScore,
    RankingHistory,
    RankingRun,
    ScoreEvidenceRecord,
    VerificationResult,
)
from app.modules.candidate_intelligence.verification.checks import overall_status
from app.modules.candidate_intelligence.types import VerificationResultData


async def compare_applications(
    db: AsyncSession,
    job_id: UUID,
    company_id: UUID,
    application_ids: list[UUID],
) -> dict:
    requested = list(application_ids)
    apps = (await db.execute(
        select(Application).where(
            Application.id.in_(requested),
            Application.job_id == job_id,
            Application.company_id == company_id,
        )
    )).scalars().all()
    by_id = {app.id: app for app in apps}
    invalid = [str(app_id) for app_id in requested if app_id not in by_id]
    if invalid:
        raise HTTPException(status_code=422, detail={
            "code": "applications_out_of_job",
            "message": "Every application must belong to the requested job and company.",
            "application_ids": invalid,
        })

    cfg = get_intelligence_settings()
    score_rows = (await db.execute(
        select(CandidateScore).where(
            CandidateScore.application_id.in_(requested),
            CandidateScore.job_id == job_id,
            CandidateScore.company_id == company_id,
            CandidateScore.scoring_version == cfg.scoring_version,
        ).order_by(CandidateScore.created_at.desc(), CandidateScore.id.desc())
    )).scalars().all()
    scores = {}
    for row in score_rows:
        scores.setdefault(row.application_id, row)
    unscored = [str(app_id) for app_id in requested if app_id not in scores]
    if unscored:
        raise HTTPException(status_code=409, detail={
            "code": "applications_not_scored",
            "message": "Every application must have a current persisted score.",
            "application_ids": unscored,
        })

    score_ids = [scores[app_id].id for app_id in requested]
    evidence_rows = (await db.execute(
        select(ScoreEvidenceRecord).where(ScoreEvidenceRecord.score_id.in_(score_ids))
    )).scalars().all()
    evidence_by_score: dict[UUID, list[ScoreEvidenceRecord]] = {score_id: [] for score_id in score_ids}
    for item in evidence_rows:
        evidence_by_score[item.score_id].append(item)
    requirements = (await db.execute(
        select(JobRequirement).where(JobRequirement.job_id == job_id).order_by(JobRequirement.id)
    )).scalars().all()
    candidates = (await db.execute(
        select(Candidate).where(Candidate.id.in_([by_id[app_id].candidate_id for app_id in requested]))
    )).scalars().all()
    candidate_by_id = {item.id: item for item in candidates}

    latest_run = (await db.execute(
        select(RankingRun).where(RankingRun.job_id == job_id)
        .order_by(RankingRun.created_at.desc(), RankingRun.id.desc()).limit(1)
    )).scalar_one_or_none()
    rank_by_app: dict[UUID, int] = {}
    if latest_run:
        history = (await db.execute(select(RankingHistory).where(
            RankingHistory.job_id == job_id,
            RankingHistory.run_id == latest_run.run_id,
            RankingHistory.application_id.in_(requested),
        ))).scalars().all()
        rank_by_app = {row.application_id: row.rank for row in history if row.application_id and row.rank}

    verification_rows = (await db.execute(select(VerificationResult).where(
        VerificationResult.application_id.in_(requested)
    ).order_by(VerificationResult.created_at.desc(), VerificationResult.id.desc()))).scalars().all()
    checks_by_app: dict[UUID, list[VerificationResult]] = {app_id: [] for app_id in requested}
    for row in verification_rows:
        if not any(existing.check_type == row.check_type for existing in checks_by_app[row.application_id]):
            checks_by_app[row.application_id].append(row)
    verification_by_app = {
        app_id: overall_status([
            VerificationResultData(row.check_type, row.status, row.signal, row.details)
            for row in checks_by_app[app_id]
        ])
        for app_id in requested
    }

    application_details = []
    for app_id in requested:
        app, score = by_id[app_id], scores[app_id]
        candidate = candidate_by_id.get(app.candidate_id)
        application_details.append({
            "id": str(app.id), "display_name": candidate.full_name if candidate else None,
            "status": app.status, "total_score": str(score.score) if score.score is not None else None,
            "lower_bound": str(score.score_lower_bound) if score.score_lower_bound is not None else None,
            "upper_bound": str(score.score_upper_bound) if score.score_upper_bound is not None else None,
            "data_completeness": str(score.data_completeness), "eligibility": score.eligibility,
            "rank": rank_by_app.get(app_id), "verification_status": verification_by_app[app_id],
        })

    category_names = sorted({
        category for app_id in requested for category in (scores[app_id].category_detail or {})
    })
    category_data: dict[str, list[dict]] = {}
    for category in category_names:
        category_data[category] = []
        for app_id in requested:
            detail = (scores[app_id].category_detail or {}).get(category, {})
            match = detail.get("match")
            weight = detail.get("weight")
            contribution = detail.get("weighted_contribution")
            if contribution is None and match is not None and weight is not None:
                contribution = Decimal(str(match)) * Decimal(str(weight))
            category_data[category].append({
                "application_id": str(app_id), "match": match, "status": detail.get("status", "unknown"),
                "weighted_contribution": str(contribution) if contribution is not None else None,
            })

    skill_requirements = [r for r in requirements if getattr(r.category, "value", r.category) == "skills"]
    skill_coverage = []
    skill_by_requirement: dict[str, list[dict]] = {}
    for requirement in skill_requirements:
        rows = []
        for app_id in requested:
            score = scores[app_id]
            relevant = [item for item in evidence_by_score[score.id]
                        if (item.requirement_term or "").casefold() == requirement.name.casefold()]
            by_type = {item.signal_type: item for item in relevant}
            evidence = next((by_type[key] for key in ("exact_skill_match", "alias_skill_match", "semantic_similarity") if key in by_type), None)
            if evidence:
                result = {"exact_skill_match": "exact", "alias_skill_match": "alias", "semantic_similarity": "semantic"}[evidence.signal_type]
                credit = str(evidence.value) if evidence.value is not None else None
                evidence_ids = [evidence.evidence_id]
            else:
                category_status = ((score.category_detail or {}).get("skills") or {}).get("status")
                result = "unknown" if category_status == "unknown" else "none"
                credit, evidence_ids = None, []
            rows.append({"application_id": str(app_id), "result": result, "credit": credit, "evidence_ids": evidence_ids})
        requirement_row = {
            "requirement_id": str(requirement.id), "name": requirement.name,
            "mandatory": bool(requirement.is_mandatory), "weight": str(requirement.weight),
            "applications": rows,
        }
        skill_coverage.append(requirement_row)
        skill_by_requirement[str(requirement.id)] = rows

    mandatory_coverage = []
    mandatory_by_requirement: dict[str, list[dict]] = {}
    for app_id in requested:
        results = scores[app_id].mandatory_results or []
        counts = {status: sum(1 for item in results if item.get("status") == status)
                  for status in ("met", "not_met", "unknown")}
        mandatory_coverage.append({
            "application_id": str(app_id), "counts": counts,
            "requirements": results,
        })
        for item in results:
            mandatory_by_requirement.setdefault(str(item.get("requirement_id")), []).append({
                "application_id": str(app_id), "status": item.get("status"),
                "evidence_ids": item.get("evidence_ids", []),
            })

    differences = []
    for category in category_names:
        rows = category_data[category]
        known = [Decimal(str(row["match"])) for row in rows if row["match"] is not None]
        if len(known) >= 2 and max(known) - min(known) >= Decimal("0.10"):
            differences.append({
                "type": "category_spread", "description": f"{category} match values differ by at least 0.10.",
                "application_ids": [row["application_id"] for row in rows], "evidence_ids": [],
                "requirement_id": category, "values": [{"application_id": row["application_id"], "match": row["match"]} for row in rows],
            })
    for req_id, rows in skill_by_requirement.items():
        if len({row["result"] for row in rows}) > 1:
            differences.append({
                "type": "skill_result", "description": "Skill evidence results differ for this requirement.",
                "application_ids": [row["application_id"] for row in rows],
                "evidence_ids": sorted({e for row in rows for e in row["evidence_ids"]}), "requirement_id": req_id,
            })
    for req_id, rows in mandatory_by_requirement.items():
        if len({row["status"] for row in rows}) > 1:
            differences.append({
                "type": "mandatory_status", "description": "Mandatory requirement evidence statuses differ.",
                "application_ids": [row["application_id"] for row in rows],
                "evidence_ids": sorted({e for row in rows for e in row["evidence_ids"]}), "requirement_id": req_id,
            })
    if len(set(verification_by_app.values())) > 1:
        differences.append({
            "type": "verification_status", "description": "Verification status results differ.",
            "application_ids": [str(app_id) for app_id in requested], "evidence_ids": [],
            "requirement_id": "",
        })
    type_order = {"category_spread": 0, "skill_result": 1, "mandatory_status": 2, "verification_status": 3}
    differences.sort(key=lambda item: (type_order[item["type"]], item["requirement_id"]))
    for item in differences:
        item.pop("requirement_id", None)
    return {
        "applications": application_details, "categories": category_data,
        "skill_coverage": skill_coverage, "mandatory_coverage": mandatory_coverage,
        "differences": differences,
        "disclaimers": ["Comparison shows evidence differences only; it does not recommend a candidate."],
    }
