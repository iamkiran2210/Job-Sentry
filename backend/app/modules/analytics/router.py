"""Company-scoped, read-only analytics over persisted recruitment records."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from uuid import UUID

from app.ai_features.models.application import Application
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.resume import Resume
from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.core.exceptions import NotFoundException
from app.models.job import Job, JobStatus
from app.models.job_requirement import JobRequirement
from app.models.user import User
from app.modules.application_status.models import ApplicationStatusHistory
from app.modules.candidate_intelligence.config import get_intelligence_settings
from app.modules.candidate_intelligence.models import (
    CandidateScore,
    RankingHistory,
    VerificationResult,
)
from app.modules.candidate_intelligence.models import ScoreEvidenceRecord
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, exists, func, select
from sqlalchemy import text, true
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _not_deleted_tombstone():
    """Exclude audit-only tombstone applications left behind when a candidate or application is deleted.

    When an audited candidate/application is soft-deleted (non-purge), candidate_id is set to NULL,
    all Resume rows are removed, and status is set to 'withdrawn' while RankingHistory /
    ApplicationStatusHistory / CandidateScore rows remain for compliance. Those deleted records
    must not inflate live KPIs, distributions, pipelines, or job aggregates.
    """
    has_resume = exists(select(1).where(Resume.application_id == Application.id))
    has_audit_or_score = (
            exists(select(1).where(RankingHistory.application_id == Application.id))
            | exists(select(1).where(ApplicationStatusHistory.application_id == Application.id))
            | exists(select(1).where(CandidateScore.application_id == Application.id))
    )
    is_tombstone = (
            Application.candidate_id.is_(None)
            & (Application.status == "withdrawn")
            & (~has_resume)
            & has_audit_or_score
    )
    return ~is_tombstone


def _date_window(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    today = datetime.now(timezone.utc).date()
    end = date_to or today
    start = date_from or end - timedelta(days=89)
    if start > end:
        raise HTTPException(status_code=422, detail="date_from must be on or before date_to")
    if (end - start).days > 365:
        raise HTTPException(status_code=422, detail="date range cannot exceed 366 days")
    return start, end


async def _scope(
    db: AsyncSession,
    user: User,
    date_from: date | None,
    date_to: date | None,
    job_id: UUID | None,
    company_id: UUID | None,
):
    start, end = _date_window(date_from, date_to)
    resolved_company = user.company_id
    if resolved_company is None:
        raise HTTPException(status_code=403, detail="Company membership required")
    if company_id is not None and company_id != resolved_company:
        raise HTTPException(status_code=403, detail="Company membership required")
    if job_id is not None:
        job = (
            await db.execute(
                select(Job).where(Job.id == job_id, Job.company_id == resolved_company)
            )
        ).scalar_one_or_none()
        if job is None:
            raise NotFoundException("Job not found")
    start_at = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    app_query = (
        select(Application)
        .join(Job, Job.id == Application.job_id)
        .where(
            Application.company_id == resolved_company,
            Application.created_at >= start_at,
            Application.created_at < end_at,
            _not_deleted_tombstone(),
        )
    )
    if job_id is not None:
        app_query = app_query.where(Application.job_id == job_id)
    return resolved_company, start, end, app_query


def _latest_scores(company_id: UUID):
    cfg = get_intelligence_settings()
    ranked = (
        select(
            CandidateScore.id.label("score_id"),
            CandidateScore.application_id.label("application_id"),
            CandidateScore.score.label("score"),
            CandidateScore.eligibility.label("eligibility"),
            CandidateScore.data_completeness.label("data_completeness"),
            CandidateScore.review_signals.label("review_signals"),
            func.row_number()
            .over(
                partition_by=CandidateScore.application_id,
                order_by=(CandidateScore.created_at.desc(), CandidateScore.id.desc()),
            )
            .label("row_number"),
        )
        .where(
            CandidateScore.company_id == company_id,
            CandidateScore.scoring_version == cfg.scoring_version,
        )
        .subquery()
    )
    return select(ranked).where(ranked.c.row_number == 1).subquery()


def _common_filters(date_from, date_to, job_id, company_id):
    return {
        "date_from": date_from,
        "date_to": date_to,
        "job_id": job_id,
        "company_id": company_id,
    }


async def _trend(db, query, start: date, end: date, interval: Literal["day", "week", "month"]):
    app_sq = query.subquery()
    bucket = func.date_trunc(interval, app_sq.c.created_at)
    records = (
        await db.execute(
            select(bucket.label("bucket"), func.count(app_sq.c.id))
            .group_by(bucket)
            .order_by(bucket)
        )
    ).all()
    counts = {row[0].date(): row[1] for row in records}
    cursor = start
    items = []
    while cursor <= end:
        if interval == "day":
            key = cursor
            cursor += timedelta(days=1)
        elif interval == "week":
            key = cursor - timedelta(days=cursor.weekday())
            cursor += timedelta(days=7)
        else:
            key = cursor.replace(day=1)
            cursor = (
                key.replace(year=key.year + 1, month=1)
                if key.month == 12
                else key.replace(month=key.month + 1)
            )
        items.append({"bucket": key.isoformat(), "applications": counts.get(key, 0)})
    return items


@router.get(
    "/overview", response_model=dict, summary="Read company recruitment KPIs and applicant trend"
)
async def overview(
    date_from: date | None = None,
    date_to: date | None = None,
    job_id: UUID | None = None,
    company_id: UUID | None = None,
    interval: Literal["day", "week", "month"] = "week",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    company, start, end, query = await _scope(db, user, date_from, date_to, job_id, company_id)
    app_sq = query.subquery()
    statuses = dict(
        (await db.execute(select(app_sq.c.status, func.count()).group_by(app_sq.c.status))).all()
    )
    total = sum(statuses.values())
    score_sq = _latest_scores(company)
    score_stats = (
        await db.execute(
            select(
                func.avg(score_sq.c.score),
                func.percentile_cont(0.5).within_group(score_sq.c.score),
                func.sum(case((score_sq.c.eligibility == "needs_review", 1), else_=0)),
            ).select_from(app_sq.outerjoin(score_sq, score_sq.c.application_id == app_sq.c.id))
        )
    ).one()
    filtered_scores = score_sq.join(app_sq, score_sq.c.application_id == app_sq.c.id)
    reviewed = (
        await db.execute(
            select(func.count())
            .select_from(filtered_scores)
            .where(score_sq.c.eligibility == "needs_review")
        )
    ).scalar_one()
    scored_count = (
        await db.execute(
            select(func.count()).select_from(
                score_sq.join(app_sq, score_sq.c.application_id == app_sq.c.id)
            )
        )
    ).scalar_one()
    active_query = (
        select(func.count())
        .select_from(Job)
        .where(Job.company_id == company, Job.status == JobStatus.ACTIVE)
    )
    if job_id is not None:
        active_query = active_query.where(Job.id == job_id)
    active_jobs = (await db.execute(active_query)).scalar_one()
    applied_times = (
        select(
            ApplicationStatusHistory.application_id,
            func.min(
                case(
                    (
                        ApplicationStatusHistory.to_status == "applied",
                        ApplicationStatusHistory.created_at,
                    )
                )
            ).label("applied_at"),
            func.min(
                case(
                    (
                        ApplicationStatusHistory.to_status == "analyzed",
                        ApplicationStatusHistory.created_at,
                    )
                )
            ).label("analyzed_at"),
        )
        .where(
            ApplicationStatusHistory.company_id == company,
            ApplicationStatusHistory.application_id.in_(select(app_sq.c.id)),
        )
        .group_by(ApplicationStatusHistory.application_id)
        .subquery()
    )
    avg_hours = (
        await db.execute(
            select(
                func.avg(
                    func.extract("epoch", applied_times.c.analyzed_at - applied_times.c.applied_at)
                    / 3600
                )
            ).where(
                applied_times.c.analyzed_at.is_not(None), applied_times.c.applied_at.is_not(None)
            )
        )
    ).scalar_one()
    trend = await _trend(db, query, start, end, interval)
    return {
        "data": {
            "kpis": {
                "total_applications": total,
                "open_jobs": active_jobs,
                "applications_per_status": {
                    status: statuses.get(status, 0)
                    for status in (
                        "applied",
                        "processing",
                        "analyzed",
                        "shortlisted",
                        "rejected",
                        "withdrawn",
                    )
                },
                "analyzed_count": statuses.get("analyzed", 0),
                "shortlisted_count": statuses.get("shortlisted", 0),
                "rejected_count": statuses.get("rejected", 0),
                "withdrawn_count": statuses.get("withdrawn", 0),
                "average_latest_score": float(score_stats[0]) if score_stats[0] is not None else 0,
                "median_latest_score": float(score_stats[1]) if score_stats[1] is not None else 0,
                "share_needing_review": (reviewed / scored_count) if scored_count else 0,
                "average_hours_applied_to_analyzed": float(avg_hours)
                if avg_hours is not None
                else 0,
            },
            "trend": {"interval": interval, "items": trend},
            "filters_applied": _common_filters(start, end, job_id, company_id),
        }
    }


@router.get("/jobs", response_model=dict, summary="List company jobs with SQL applicant aggregates")
async def jobs(
    date_from: date | None = None,
    date_to: date | None = None,
    job_id: UUID | None = None,
    company_id: UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("-created_at"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    company, start, end, app_query = await _scope(db, user, date_from, date_to, job_id, company_id)
    app_sq = app_query.subquery()
    score_sq = _latest_scores(company)
    allowed = {
        "applications": func.count(app_sq.c.id),
        "analyzed": func.sum(case((app_sq.c.status == "analyzed", 1), else_=0)),
        "shortlisted": func.sum(case((app_sq.c.status == "shortlisted", 1), else_=0)),
        "avg_score": func.avg(score_sq.c.score),
        "created_at": Job.created_at,
    }
    ordering = []
    for token in sort.split(","):
        field = token[1:] if token.startswith("-") else token
        if field not in allowed:
            raise HTTPException(
                status_code=422, detail=f"Unknown sort field; allowed: {', '.join(allowed)}"
            )
        ordering.append(allowed[field].desc() if token.startswith("-") else allowed[field].asc())
    query = (
        select(
            Job.id,
            Job.title,
            Job.created_at,
            func.count(app_sq.c.id).label("applications"),
            func.sum(case((app_sq.c.status == "applied", 1), else_=0)).label("applied"),
            func.sum(case((app_sq.c.status == "processing", 1), else_=0)).label("processing"),
            func.sum(case((app_sq.c.status == "analyzed", 1), else_=0)).label("analyzed"),
            func.sum(case((app_sq.c.status == "shortlisted", 1), else_=0)).label("shortlisted"),
            func.sum(case((app_sq.c.status == "rejected", 1), else_=0)).label("rejected"),
            func.sum(case((app_sq.c.status == "withdrawn", 1), else_=0)).label("withdrawn"),
            func.avg(score_sq.c.score).label("avg_score"),
            func.min(score_sq.c.score).label("min_score"),
            func.max(score_sq.c.score).label("max_score"),
            func.sum(case((score_sq.c.eligibility == "eligible", 1), else_=0)).label("eligible"),
            func.sum(case((score_sq.c.eligibility == "needs_review", 1), else_=0)).label(
                "needs_review"
            ),
            func.sum(case((score_sq.c.eligibility == "potentially_ineligible", 1), else_=0)).label(
                "potentially_ineligible"
            ),
        )
        .select_from(Job)
        .outerjoin(app_sq, app_sq.c.job_id == Job.id)
        .outerjoin(score_sq, score_sq.c.application_id == app_sq.c.id)
        .where(Job.company_id == company)
        .group_by(Job.id)
    )
    if job_id is not None:
        query = query.where(Job.id == job_id)
    total_query = select(func.count()).select_from(
        select(Job.id).where(Job.company_id == company).subquery()
    )
    if job_id is not None:
        total_query = select(func.count()).select_from(
            select(Job.id).where(Job.company_id == company, Job.id == job_id).subquery()
        )
    total = (await db.execute(total_query)).scalar_one()
    rows = (
        await db.execute(
            query.order_by(*ordering, Job.id.asc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    return {
        "data": {
            "items": [
                {
                    key: (
                        str(value)
                        if isinstance(value, UUID)
                        else value.isoformat()
                        if isinstance(value, datetime)
                        else float(value)
                        if key in {"avg_score", "min_score", "max_score"} and value is not None
                        else value
                    )
                    for key, value in row._mapping.items()
                }
                for row in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
            "filters_applied": _common_filters(start, end, job_id, company_id),
        }
    }


@router.get(
    "/candidates",
    response_model=dict,
    summary="Read aggregate score and verification distributions",
)
async def candidates(
    date_from: date | None = None,
    date_to: date | None = None,
    job_id: UUID | None = None,
    company_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    company, start, end, app_query = await _scope(db, user, date_from, date_to, job_id, company_id)
    app_sq, score_sq = app_query.subquery(), _latest_scores(company)
    scores = score_sq.join(app_sq, score_sq.c.application_id == app_sq.c.id)
    total = (await db.execute(select(func.count()).select_from(app_sq))).scalar_one()
    buckets = []
    for lower in range(0, 100, 10):
        upper = lower + 10
        condition = (score_sq.c.score >= lower) & (score_sq.c.score < upper)
        if upper == 100:
            condition = (score_sq.c.score >= lower) & (score_sq.c.score <= 100)
        count = (
            await db.execute(select(func.count()).select_from(scores).where(condition))
        ).scalar_one()
        buckets.append({"bucket": f"{lower}-{upper}", "count": count})
    unscored = (
        await db.execute(
            select(func.count())
            .select_from(app_sq.outerjoin(score_sq, score_sq.c.application_id == app_sq.c.id))
            .where(score_sq.c.application_id.is_(None) | score_sq.c.score.is_(None))
        )
    ).scalar_one()
    buckets.append({"bucket": "unscored", "count": unscored})
    eligibility_rows = (
        await db.execute(
            select(score_sq.c.eligibility, func.count())
            .select_from(scores)
            .group_by(score_sq.c.eligibility)
        )
    ).all()
    completeness = []
    for label, lower, upper, include_upper in (
            ("0-0.25", 0, 0.25, False),
            ("0.25-0.5", 0.25, 0.5, False),
            ("0.5-0.75", 0.5, 0.75, False),
            ("0.75-1.0", 0.75, 1, True),
    ):
        condition = (score_sq.c.data_completeness >= lower) & (
            (score_sq.c.data_completeness <= upper)
            if include_upper
            else (score_sq.c.data_completeness < upper)
        )
        count = (
            await db.execute(select(func.count()).select_from(scores).where(condition))
        ).scalar_one()
        completeness.append({"bucket": label, "count": count})
    check_ranked = (
        select(
            VerificationResult.application_id,
            VerificationResult.check_type,
            VerificationResult.status,
            func.row_number()
            .over(
                partition_by=(VerificationResult.application_id, VerificationResult.check_type),
                order_by=(VerificationResult.created_at.desc(), VerificationResult.id.desc()),
            )
            .label("rn"),
        )
        .where(
            VerificationResult.company_id == company,
            VerificationResult.application_id.in_(select(app_sq.c.id)),
        )
        .subquery()
    )
    severity = func.max(
        case(
            (check_ranked.c.status == "failed", 4),
            (check_ranked.c.status == "needs_review", 3),
            (check_ranked.c.status == "not_verified", 2),
            (check_ranked.c.status == "passed", 1),
            else_=0,
        )
    ).label("severity")
    overall = (
        select(check_ranked.c.application_id, severity)
        .where(check_ranked.c.rn == 1)
        .group_by(check_ranked.c.application_id)
        .subquery()
    )
    verification_case = case(
        (overall.c.severity == 4, "failed"),
        (overall.c.severity == 3, "needs_review"),
        (overall.c.severity == 2, "not_verified"),
        (overall.c.severity.is_(None), "not_verified"),
        else_="passed",
    )
    verification_rows = (
        await db.execute(
            select(verification_case.label("status"), func.count())
            .select_from(app_sq.outerjoin(overall, overall.c.application_id == app_sq.c.id))
            .group_by(verification_case)
        )
    ).all()
    signal_function = (
        func.jsonb_array_elements_text(score_sq.c.review_signals).table_valued("value").lateral()
    )
    signal_rows = (
        await db.execute(
            select(signal_function.c.value, func.count())
            .select_from(scores.join(signal_function, true()))
            .group_by(signal_function.c.value)
            .order_by(func.count().desc(), signal_function.c.value)
            .limit(20)
        )
    ).all()
    return {
        "data": {
            "score_distribution": buckets,
            "eligibility_distribution": {str(status): count for status, count in eligibility_rows},
            "verification_distribution": {
                str(status): count for status, count in verification_rows
            },
            "data_completeness_distribution": completeness,
            "review_signal_frequency": [
                {"code": code, "count": count} for code, count in signal_rows
            ],
            "filters_applied": _common_filters(start, end, job_id, company_id),
        }
    }


@router.get(
    "/skills",
    response_model=dict,
    summary="Read aggregate candidate and requirement skill coverage",
)
async def skills(
    date_from: date | None = None,
    date_to: date | None = None,
    job_id: UUID | None = None,
    company_id: UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    company, start, end, app_query = await _scope(db, user, date_from, date_to, job_id, company_id)
    app_sq = app_query.subquery()
    total = (await db.execute(select(func.count()).select_from(app_sq))).scalar_one()
    params = {
        "company_id": company,
        "start_at": datetime.combine(start, time.min, tzinfo=timezone.utc),
        "end_at": datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc),
        "job_id": job_id,
        "limit": limit,
    }
    top_skills = (
        await db.execute(
            text("""
        SELECT lower(coalesce(skill.value->>'canonical_name', skill.value->>'name')) AS skill,
               count(DISTINCT coalesce(a.candidate_id, a.id)) AS candidate_count
        FROM applications a JOIN jobs j ON j.id = a.job_id
        JOIN resumes r ON r.application_id = a.id
        JOIN extracted_profiles ep ON ep.resume_id = r.id
        CROSS JOIN LATERAL jsonb_array_elements(coalesce(ep.profile_data->'skills', '[]'::jsonb)) AS skill(value)
        WHERE a.company_id = :company_id AND a.created_at >= :start_at AND a.created_at < :end_at
          AND (CAST(:job_id AS uuid) IS NULL OR a.job_id = CAST(:job_id AS uuid))
          AND coalesce(skill.value->>'canonical_name', skill.value->>'name') IS NOT NULL
        GROUP BY 1 ORDER BY candidate_count DESC, skill ASC LIMIT :limit
    """),
            params,
        )
    ).all()
    total_applicants = max(total, 1)
    score_sq = _latest_scores(company)
    required = (
        await db.execute(
            select(
                JobRequirement.id,
                JobRequirement.name,
                JobRequirement.weight,
                JobRequirement.is_mandatory,
                func.count(func.distinct(app_sq.c.id))
                .filter(
                    ScoreEvidenceRecord.signal_type.in_(("exact_skill_match", "alias_skill_match"))
                )
                .label("matched"),
            )
            .select_from(JobRequirement)
            .join(app_sq, JobRequirement.job_id == app_sq.c.job_id)
            .outerjoin(score_sq, score_sq.c.application_id == app_sq.c.id)
            .outerjoin(
                ScoreEvidenceRecord,
                (ScoreEvidenceRecord.score_id == score_sq.c.score_id)
                & (
                        func.lower(ScoreEvidenceRecord.requirement_term)
                        == func.lower(JobRequirement.name)
                ),
            )
            .where(
                JobRequirement.category == "skills",
                JobRequirement.job_id.in_(select(app_sq.c.job_id).distinct()),
            )
            .group_by(
                JobRequirement.id,
                JobRequirement.name,
                JobRequirement.weight,
                JobRequirement.is_mandatory,
            )
            .order_by(JobRequirement.name, JobRequirement.id)
        )
    ).all()
    return {
        "data": {
            "top_candidate_skills": [
                {
                    "skill": row.skill,
                    "candidate_count": row.candidate_count,
                    "share": row.candidate_count / total_applicants,
                }
                for row in top_skills
            ],
            "top_required_skills": [
                {
                    "requirement_id": str(row.id),
                    "skill": row.name,
                    "mandatory": row.is_mandatory,
                    "weight": row.weight,
                    "coverage_rate": row.matched / total_applicants,
                }
                for row in required
            ],
            "filters_applied": _common_filters(start, end, job_id, company_id),
        }
    }


@router.get(
    "/pipeline", response_model=dict, summary="Read status funnel and resume processing outcomes"
)
async def pipeline(
    date_from: date | None = None,
    date_to: date | None = None,
    job_id: UUID | None = None,
    company_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    company, start, end, app_query = await _scope(db, user, date_from, date_to, job_id, company_id)
    app_sq = app_query.subquery()
    statuses = dict(
        (await db.execute(select(app_sq.c.status, func.count()).group_by(app_sq.c.status))).all()
    )
    resume_query = (
        select(Resume)
        .join(app_sq, app_sq.c.id == Resume.application_id)
        .where(Resume.company_id == company)
    )
    resume_sq = resume_query.subquery()
    processing = (
        await db.execute(
            select(
                func.sum(case((resume_sq.c.status == "completed", 1), else_=0)),
                func.sum(case((resume_sq.c.status == "failed", 1), else_=0)),
                func.sum(
                    case(
                        (
                            resume_sq.c.status.in_(
                                ("uploaded", "queued", "extracting", "analyzing")
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                func.avg(
                    func.extract("epoch", resume_sq.c.completed_at - resume_sq.c.started_at)
                ).filter(
                    resume_sq.c.completed_at.is_not(None), resume_sq.c.started_at.is_not(None)
                ),
                func.percentile_cont(0.95)
                .within_group(
                    func.extract("epoch", resume_sq.c.completed_at - resume_sq.c.started_at)
                )
                .filter(resume_sq.c.completed_at.is_not(None), resume_sq.c.started_at.is_not(None)),
            )
        )
    ).one()
    failures = (
        await db.execute(
            select(resume_sq.c.failure_code, func.count())
            .where(resume_sq.c.status == "failed", resume_sq.c.failure_code.is_not(None))
            .group_by(resume_sq.c.failure_code)
            .order_by(func.count().desc(), resume_sq.c.failure_code)
            .limit(20)
        )
    ).all()
    analyzed, shortlisted, rejected = (
        statuses.get(item, 0) for item in ("analyzed", "shortlisted", "rejected")
    )
    return {
        "data": {
            "funnel": [
                {"status": status, "count": statuses.get(status, 0)}
                for status in (
                    "applied",
                    "processing",
                    "analyzed",
                    "shortlisted",
                    "rejected",
                    "withdrawn",
                )
            ],
            "conversion": {
                "analyzed_to_shortlisted_rate": shortlisted / analyzed if analyzed else 0,
                "shortlisted_to_rejected_rate": rejected / shortlisted if shortlisted else 0,
            },
            "processing_outcomes": {
                "succeeded": int(processing[0] or 0),
                "failed": int(processing[1] or 0),
                "in_progress": int(processing[2] or 0),
                "average_processing_seconds": float(processing[3])
                if processing[3] is not None
                else 0,
                "p95_processing_seconds": float(processing[4]) if processing[4] is not None else 0,
            },
            "failure_reasons": [{"code": code, "count": count} for code, count in failures],
            "filters_applied": _common_filters(start, end, job_id, company_id),
        }
    }
