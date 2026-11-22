from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_features._compat import (
    get_current_active_user,
    get_db,
    is_access_denied,
    ok,
)
from app.ai_features.resumes.presenters import profile_out
from app.ai_features.resumes.service import NotFound
from app.ai_features.schemas.resume import (
    ApplicantStatus,
    ApplicationBrief,
    CandidateDeletedOut,
    CandidateOut,
    CandidateUpdateIn,
    IdentitySuggestionOut,
    JobApplicantOut,
)

from .service import CandidatesService

router = APIRouter(tags=["Candidates"])


def _candidate_out(cand, rows, profile, sugg) -> CandidateOut:
    return CandidateOut(
        id=cand.id,
        full_name=cand.full_name,
        email=cand.email,
        phone=cand.phone,
        created_at=cand.created_at,
        applications=[
            ApplicationBrief(
                application_id=a.id,
                job_id=a.job_id,
                status=a.status,
                resume_id=r.id,
                resume_status=r.status,
                created_at=a.created_at,
            )
            for a, r in rows
        ],
        latest_profile=profile_out(profile) if profile else None,
        identity_review=[IdentitySuggestionOut.model_validate(s) for s in sugg],
    )


@router.get(
    "/candidates/{candidate_id}",
    summary="Candidate with applications, latest extracted profile and identity-review hints",
)
async def get_candidate(
        candidate_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        current_user=Depends(get_current_active_user),
):
    try:
        cand, rows, profile, sugg = await CandidatesService.get_candidate_bundle(
            db, current_user, candidate_id
        )
    except NotFound:
        raise HTTPException(404, "Not found") from None
    return ok(_candidate_out(cand, rows, profile, sugg))


@router.patch(
    "/candidates/{candidate_id}",
    summary="Manually update candidate identity and extracted profile details",
)
async def update_candidate(
        candidate_id: uuid.UUID,
        payload: CandidateUpdateIn,
        db: AsyncSession = Depends(get_db),
        current_user=Depends(get_current_active_user),
):
    try:
        cand, rows, profile, sugg = await CandidatesService.update_candidate(
            db, current_user, candidate_id, payload
        )
    except NotFound:
        raise HTTPException(404, "Not found") from None
    return ok(_candidate_out(cand, rows, profile, sugg), message="Candidate details updated")


@router.delete(
    "/candidates",
    summary="Clean-delete all candidates and their resumes/applications for the company (Data Explorer)",
)
async def delete_all_candidates(
        db: AsyncSession = Depends(get_db),
        current_user=Depends(get_current_active_user),
):
    try:
        counts = await CandidatesService.purge_all_candidates(db, current_user)
    except NotFound:
        raise HTTPException(404, "Not found") from None
    return ok(counts, message="All candidates and associated records clean-deleted")


@router.delete(
    "/candidates/{candidate_id}",
    summary="Delete a candidate (pass purge=true from Data Explorer for full clean delete of all records)",
)
async def delete_candidate(
        candidate_id: uuid.UUID,
        purge: bool = Query(
            False,
            description="When true (Data Explorer clean delete), permanently removes candidate, applications, resumes, scores, verifications, and history records.",
        ),
        db: AsyncSession = Depends(get_db),
        current_user=Depends(get_current_active_user),
):
    try:
        if purge:
            counts = await CandidatesService.purge_candidate(db, current_user, candidate_id)
            return ok(
                CandidateDeletedOut(
                    candidate_id=candidate_id,
                    deleted=True,
                    clean_deleted=True,
                    **counts,
                ),
                message="Candidate and all associated records clean-deleted",
            )
        cleaned = await CandidatesService.delete_candidate(db, current_user, candidate_id)
    except NotFound:
        raise HTTPException(404, "Not found") from None
    return ok(
        CandidateDeletedOut(candidate_id=candidate_id, deleted=True, applications_cleaned=cleaned),
        message="Candidate deleted",
    )


@router.get(
    "/jobs/{job_id}/applicants",
    summary="List applicants for a specific job (requires company membership or job access grant)",
)
@router.get(
    "/jobs/{job_id}/applications",
    summary="List applications for a specific job (alias)",
    include_in_schema=False,
)
async def list_job_applicants(
        job_id: uuid.UUID,
        status: Optional[ApplicantStatus] = Query(
            None, description="Filter applicants by application status"
        ),
        db: AsyncSession = Depends(get_db),
        current_user=Depends(get_current_active_user),
):
    try:
        applicants = await CandidatesService.list_job_applicants(
            db, current_user, job_id, status=status
        )
    except NotFound:
        raise HTTPException(404, "Job not found") from None
    except Exception as exc:
        if is_access_denied(exc):
            status_code = getattr(exc, "status_code", 404)
            detail = getattr(exc, "message", getattr(exc, "detail", "Not found"))
            raise HTTPException(status_code, detail=detail) from None
        raise
    return ok(applicants)
