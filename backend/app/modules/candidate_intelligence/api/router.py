from __future__ import annotations

import uuid

from app.ai_features.models.application import Application
from app.ai_features.models.resume import Resume
from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.core.exceptions import NotFoundException
from app.models.user import User
from app.modules.candidate_intelligence.comparison import compare_applications
from app.modules.candidate_intelligence.models import RankingHistory, RankingRun
from app.modules.candidate_intelligence.notifications import send_candidate_notification
from app.modules.candidate_intelligence.ranking.decision_agents import (
    list_decision_agents,
    normalize_agent_id,
)
from app.modules.candidate_intelligence.ranking.service import rank_rows
from app.modules.candidate_intelligence.schemas import (
    AnalysisResponse,
    CompareRequest,
    CompareResponse,
    DecisionAgentId,
    DecisionAgentsResponse,
    DecisionOutcome,
    NotifyCandidateRequest,
    NotifyCandidateResponse,
    RankRequest,
    RankResponse,
    RankingHistoryResponse,
    RankingResponse,
    VerifyResponse,
    Eligibility,
    VerificationStatus,
)
from app.modules.candidate_intelligence.service import CandidateIntelligenceService
from app.modules.candidate_intelligence.verification.checks import (
    compute_fraud_risk_summary,
    overall_status,
)
from app.modules.jobs.service import JobsService
from app.utils.responses import success_response
from fastapi import APIRouter, Body, Depends, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["Candidate Intelligence"])


@router.get(
    "/decision-agents",
    response_model=DecisionAgentsResponse,
    summary="List available advisory hiring decision agents",
)
async def get_decision_agents(
        user: User = Depends(get_current_active_user),  # noqa: ARG001
):
    return success_response(
        data={
            "default_agent": "balanced",
            "agents": list_decision_agents(),
        },
        message="Available decision agents",
    )


@router.post(
    "/jobs/{job_id}/compare",
    response_model=CompareResponse,
    summary="Compare persisted evidence for applications in one job",
)
async def compare_job_applications(
    job_id: uuid.UUID,
    request: CompareRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    await JobsService.get_job(db, user, job_id)
    result = await compare_applications(db, job_id, user.company_id, request.application_ids)
    return success_response(
        data=jsonable_encoder(result), message="Application evidence comparison"
    )


def _mask_contact_details(check_type: str, details: dict) -> dict:
    masked = dict(details)
    if check_type == "phone_format" and masked.get("normalized_e164"):
        value = str(masked["normalized_e164"])
        visible = value[-4:]
        masked["normalized_e164"] = "*" * max(0, len(value) - 4) + visible
    for key in ("email", "phone"):
        if masked.get(key):
            value = str(masked[key])
            masked[key] = (
                (value[:1] + "***@" + value.rsplit("@", 1)[1])
                if key == "email" and "@" in value
                else "*" * max(0, len(value) - 4) + value[-4:]
            )
    return masked


@router.post(
    "/applications/{application_id}/verify",
    response_model=VerifyResponse,
    summary="Run deterministic verification signals",
)
async def verify_application(
        application_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_current_active_user),
):
    app = (
        await db.execute(select(Application).where(Application.id == application_id))
    ).scalar_one_or_none()
    if app is None:
        raise NotFoundException("Application not found")
    await JobsService.get_job(db, user, app.job_id, require_edit=True)
    results = await CandidateIntelligenceService.verify(db, app.id)
    data = {
        "overall_status": overall_status(results),
        "checks": [
            {
                "check_type": r.check_type,
                "status": r.status,
                "signal": r.signal,
                "details": _mask_contact_details(r.check_type, r.details),
            }
            for r in results
        ],
        "fraud_risk": compute_fraud_risk_summary(results),
        "disclaimer": "These checks do not prove identity, employment or skill. A reachable public URL does not prove skills or employment.",
    }
    return success_response(data=data, message="Verification signals recorded")


@router.post(
    "/applications/{application_id}/notify",
    response_model=NotifyCandidateResponse,
    summary="Send or preview a candidate status & feedback email notification",
)
async def notify_candidate(
        application_id: uuid.UUID,
        request: NotifyCandidateRequest = Body(default=NotifyCandidateRequest()),
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_current_active_user),
):
    from app.ai_features.models.candidate import Candidate
    from app.models.job import Job

    app = (
        await db.execute(select(Application).where(Application.id == application_id))
    ).scalar_one_or_none()
    if app is None:
        raise NotFoundException("Application not found")
    await JobsService.get_job(db, user, app.job_id, require_edit=True)
    job = await db.get(Job, app.job_id)
    candidate = await db.get(Candidate, app.candidate_id) if app.candidate_id else None
    analysis = await CandidateIntelligenceService.analyze(db, app.id, pii_access=True)
    outcome = request.outcome or (
        "shortlisted"
        if app.status == "shortlisted"
           or (analysis.get("decision") or {}).get("decision") in {"strong_advance", "advance"}
        else "rejected"
    )
    feedback = request.feedback or (analysis.get("decision") or {}).get("summary")
    result = await send_candidate_notification(
        recipient_email=candidate.email if candidate and candidate.email else analysis["candidate"].get("email"),
        candidate_name=candidate.full_name if candidate and candidate.full_name else analysis["candidate"].get(
            "display_name"),
        job_title=job.title if job else "this role",
        outcome=outcome,
        score=analysis.get("score"),
        feedback=feedback,
        include_score=request.include_score,
    )
    return success_response(
        data={"application_id": str(app.id), **result},
        message="Candidate notification processed",
    )


@router.get(
    "/applications/{application_id}/analysis",
    response_model=AnalysisResponse,
    summary="Read deterministic candidate analysis",
)
async def analyze_application(
        application_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_current_active_user),
):
    app = (
        await db.execute(select(Application).where(Application.id == application_id))
    ).scalar_one_or_none()
    if app is None:
        raise NotFoundException("Application not found")
    await JobsService.get_job(db, user, app.job_id)
    pii_access = user.company_id == app.company_id
    analysis = await CandidateIntelligenceService.analyze(db, app.id, pii_access=pii_access)
    return success_response(
        data=jsonable_encoder(analysis),
        message="Candidate analysis",
    )


@router.post(
    "/jobs/{job_id}/rank",
    response_model=RankResponse,
    summary="Create a versioned ranking run for one job",
)
async def rank_job(
        job_id: uuid.UUID,
        request: RankRequest = Body(default=RankRequest()),
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_current_active_user),
):
    await JobsService.get_job(db, user, job_id, require_edit=True)
    rows = await CandidateIntelligenceService.rank(db, job_id, user.id, request.model_dump())
    return success_response(data=rows, message="Ranking run recorded")


@router.get(
    "/jobs/{job_id}/ranking",
    response_model=RankingResponse,
    summary="Read a stable page from a ranking run",
)
async def get_ranking(
        job_id: uuid.UUID,
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=100),
        offset: int | None = Query(None, ge=0),
        limit: int | None = Query(None, ge=1, le=100),
        run_id: uuid.UUID | None = None,
        eligibility: Eligibility | None = None,
        verification_status: VerificationStatus | None = None,
        min_score: float | None = Query(None, ge=0, le=100),
        max_score: float | None = Query(None, ge=0, le=100),
        status: str | None = None,
        decision_agent: DecisionAgentId | None = None,
        decision: DecisionOutcome | None = None,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_current_active_user),
):
    await JobsService.get_job(db, user, job_id)
    if min_score is not None and max_score is not None and min_score > max_score:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422, detail="min_score must be less than or equal to max_score"
        )
    resolved_offset = offset if offset is not None else (page - 1) * page_size
    resolved_limit = limit if limit is not None else page_size
    available_agents = list_decision_agents()
    query = select(RankingRun).where(RankingRun.job_id == job_id)
    if run_id:
        query = query.where(RankingRun.run_id == run_id)
    run = (
        await db.execute(
            query.order_by(RankingRun.created_at.desc(), RankingRun.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if run is None:
        if run_id:
            raise NotFoundException("Ranking run not found")
        return success_response(
            data={
                "run_id": None,
                "total_count": 0,
                "offset": resolved_offset,
                "limit": resolved_limit,
                "items": [],
                "scoring_version": None,
                "algorithm_version": None,
                "filters_applied": {},
                "decision_agent": normalize_agent_id(decision_agent),
                "available_decision_agents": available_agents,
            },
            message="No ranking run exists",
        )
    run_default_agent = (
        (run.filters_applied or {}).get("decision_agent")
        if isinstance(run.filters_applied, dict)
        else None
    )
    run_threshold = (
        (run.filters_applied or {}).get("min_accept_threshold")
        if isinstance(run.filters_applied, dict)
        else None
    )
    active_decision_agent = normalize_agent_id(decision_agent or run_default_agent)
    history = (
        await db.execute(
            select(RankingHistory)
            .where(RankingHistory.job_id == job_id, RankingHistory.run_id == run.run_id)
            .order_by(RankingHistory.rank)
            .limit(1)
        )
    ).scalar_one_or_none()
    ranked_snapshot = [dict(item) for item in (history.ranked_items or [])] if history else []
    if ranked_snapshot:
        # Exclude applications that were deleted (either hard-deleted or purged tombstones)
        snap_ids = []
        for item in ranked_snapshot:
            try:
                snap_ids.append(uuid.UUID(str(item.get("application_id"))))
            except Exception:
                continue
        if snap_ids:
            live_apps = (
                (
                    await db.execute(
                        select(Application).where(
                            Application.job_id == job_id, Application.id.in_(snap_ids)
                        )
                    )
                )
                .scalars()
                .all()
            )
            tomb_ids = [
                a.id for a in live_apps if a.candidate_id is None and a.status == "withdrawn"
            ]
            with_resumes = (
                set(
                    (
                        await db.execute(
                            select(Resume.application_id).where(
                                Resume.application_id.in_(tomb_ids)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if tomb_ids
                else set()
            )
            active_id_strs = {
                str(a.id) for a in live_apps if a.id not in (set(tomb_ids) - with_resumes)
            }
            ranked_snapshot = [
                item
                for item in ranked_snapshot
                if str(item.get("application_id")) in active_id_strs
            ]
    filtered = rank_rows(
        ranked_snapshot,
        offset=0,
        limit=len(ranked_snapshot) or 1,
        eligibility=eligibility,
        min_score=min_score,
        max_score=max_score,
        status=status,
        verification_status=verification_status,
        decision_agent=active_decision_agent,
        decision=decision,
        min_accept_threshold=run_threshold,
    )
    items = filtered[resolved_offset: resolved_offset + resolved_limit]
    filters_applied = {
        key: value
        for key, value in {
            "eligibility": eligibility,
            "verification_status": verification_status,
            "min_score": min_score,
            "max_score": max_score,
            "status": status,
            "decision_agent": decision_agent,
            "decision": decision,
        }.items()
        if value is not None
    }
    return success_response(
        data={
            "run_id": str(run.run_id),
            "total_count": len(filtered),
            "offset": resolved_offset,
            "limit": resolved_limit,
            "items": items,
            "scoring_version": run.scoring_version,
            "algorithm_version": run.algorithm_version,
            "filters_applied": filters_applied,
            "decision_agent": active_decision_agent,
            "min_accept_threshold": run_threshold,
            "available_decision_agents": available_agents,
        },
        message="Job ranking",
    )


@router.get(
    "/jobs/{job_id}/ranking/history",
    response_model=RankingHistoryResponse,
    summary="List immutable ranking runs",
)
async def ranking_history(
        job_id: uuid.UUID,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_current_active_user),
):
    await JobsService.get_job(db, user, job_id)
    rows = (
        (
            await db.execute(
                select(RankingRun)
                .where(RankingRun.job_id == job_id)
                .order_by(RankingRun.created_at.desc(), RankingRun.id.desc())
            )
        )
        .scalars()
        .all()
    )
    items = [
        {
            "run_id": str(row.run_id),
            "job_id": str(row.job_id),
            "job_requirements_hash": row.job_requirements_hash,
            "filters_applied": row.filters_applied,
            "scoring_version": row.scoring_version,
            "algorithm_version": row.algorithm_version,
            "triggered_by": str(row.triggered_by) if row.triggered_by else None,
            "config_hash": row.scoring_config_hash,
            "provider_snapshot": {
                "embedding_model": row.embedding_model,
                "embedding_version": row.embedding_model_version,
                "llm_model": row.llm_model,
                "llm_prompt_version": row.prompt_version,
            },
            "created_at": row.created_at.isoformat(),
            "count": row.counts.get("scored", 0),
        }
        for row in rows[offset: offset + limit]
    ]
    return success_response(
        data={"items": items, "offset": offset, "limit": limit}, message="Ranking history"
    )
