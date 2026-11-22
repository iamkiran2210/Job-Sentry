"""Resume upload/status/retry and application read. Registered under your API prefix (normally /api/v1)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_features.schemas.resume import (
    ApplicationDeletedOut,
    ApplicationOut,
    ResumeOut,
    ResumeStatusOut,
    UploadItem,
    UploadResult,
)

from app.ai_features._compat import get_current_active_user, get_db, ok
from .config import ResumeSettings, get_settings
from .dispatch import Dispatcher, get_dispatcher
from .errors import UploadRejected
from .presenters import resume_out, status_out
from .service import NotFound, ResumesService, RetryConflict
from .storage import ObjectStorage, get_storage
from .validation import read_upload, sanitize_filename

router = APIRouter(tags=["Resumes"])


def _not_found() -> HTTPException:
    return HTTPException(404, "Not found")  # identical for missing and no-access records


@router.post(
    "/jobs/{job_id}/resumes",
    summary="Upload one or more resumes (PDF, DOCX, JPEG, PNG); processing is asynchronous",
)
async def upload_resumes(
        job_id: uuid.UUID,
        files: list[UploadFile] = File(
            ...,
            description="One or more resumes: PDF, DOCX, JPEG or PNG (max 10 MB each).",
            # Older Swagger UI builds render OpenAPI 3.1's `contentMediaType` as a plain text array; `format: binary` always gets a file picker.
            json_schema_extra={"items": {"type": "string", "format": "binary"}},
        ),
        db: AsyncSession = Depends(get_db),
        current_user=Depends(get_current_active_user),
        storage: ObjectStorage = Depends(get_storage),
        dispatcher: Dispatcher = Depends(get_dispatcher),
        cfg: ResumeSettings = Depends(get_settings),
):
    job = await ResumesService.job_for_upload(db, current_user, job_id)
    if len(files) > cfg.max_files_per_request:
        raise HTTPException(413, f"At most {cfg.max_files_per_request} files per request.")
    items: list[UploadItem] = []
    for f in files:
        try:
            data = await read_upload(f, cfg.max_upload_bytes)
        except UploadRejected as exc:
            items.append(
                UploadItem(
                    filename=sanitize_filename(f.filename),
                    status="rejected",
                    reason_code=exc.code.value,
                    detail=exc.detail,
                )
            )
            continue
        res = await ResumesService.ingest_file(
            db,
            job=job,
            user=current_user,
            filename=f.filename,
            data=data,
            cfg=cfg,
            storage=storage,
            dispatcher=dispatcher,
        )
        items.append(UploadItem(**res.__dict__))
    accepted = any(i.status != "rejected" for i in items)
    return ok(
        UploadResult(results=items),
        "Resumes queued for processing" if accepted else "No files were accepted",
        202 if accepted else 422,
    )


@router.get(
    "/resumes/{resume_id}",
    summary="Resume metadata and extracted profile (once completed)",
)
async def get_resume(
        resume_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        current_user=Depends(get_current_active_user),
):
    try:
        r = await ResumesService.get_resume(db, current_user, resume_id)
    except NotFound:
        raise _not_found() from None
    return ok(resume_out(r, await ResumesService.get_profile(db, r.id)))


@router.get("/resumes/{resume_id}/status", summary="Processing status of a resume")
async def get_resume_status(
        resume_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        current_user=Depends(get_current_active_user),
):
    try:
        r = await ResumesService.get_resume(db, current_user, resume_id)
    except NotFound:
        raise _not_found() from None
    return ok(status_out(r))


@router.post(
    "/resumes/{resume_id}/retry",
    summary="Re-queue a failed (or never-queued) resume; needs edit access",
)
async def retry_resume(
        resume_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        current_user=Depends(get_current_active_user),
        dispatcher: Dispatcher = Depends(get_dispatcher),
        cfg: ResumeSettings = Depends(get_settings),
):
    try:
        r = await ResumesService.request_retry(db, current_user, resume_id, cfg, dispatcher)
    except NotFound:
        raise _not_found() from None
    except RetryConflict as exc:
        raise HTTPException(409, exc.reason) from None
    return ok(status_out(r), "Resume re-queued", 202)


@router.get(
    "/applications/{application_id}",
    summary="Application with its resume(s) and extracted profile",
)
async def get_application(
        application_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        current_user=Depends(get_current_active_user),
):
    try:
        app, resumes = await ResumesService.get_application(db, current_user, application_id)
    except NotFound:
        raise _not_found() from None
    outs = [resume_out(r, await ResumesService.get_profile(db, r.id)) for r in resumes]
    return ok(
        ApplicationOut(
            id=app.id,
            job_id=app.job_id,
            candidate_id=app.candidate_id,
            status=app.status,
            created_at=app.created_at,
            resumes=outs,
        )
    )


@router.delete(
    "/applications/{application_id}",
    summary="Delete a resume application and its uploaded resume(s); needs edit access",
)
async def delete_application(
        application_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        current_user=Depends(get_current_active_user),
        storage: ObjectStorage = Depends(get_storage),
):
    try:
        app_id, resumes_deleted, audit_preserved = await ResumesService.delete_application(
            db, current_user, application_id, storage=storage
        )
    except NotFound:
        raise _not_found() from None
    return ok(
        ApplicationDeletedOut(
            application_id=app_id,
            deleted=True,
            resumes_deleted=resumes_deleted,
            audit_preserved=audit_preserved,
        ),
        "Application deleted",
    )


@router.delete(
    "/resumes/{resume_id}",
    summary="Delete an uploaded resume (and its application if no other resumes remain); needs edit access",
)
async def delete_resume(
        resume_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        current_user=Depends(get_current_active_user),
        storage: ObjectStorage = Depends(get_storage),
):
    try:
        app_id, resumes_deleted, audit_preserved = await ResumesService.delete_resume(
            db, current_user, resume_id, storage=storage
        )
    except NotFound:
        raise _not_found() from None
    return ok(
        ApplicationDeletedOut(
            application_id=app_id,
            deleted=True,
            resumes_deleted=resumes_deleted,
            audit_preserved=audit_preserved,
        ),
        "Resume application deleted",
    )
