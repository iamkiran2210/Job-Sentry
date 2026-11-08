from __future__ import annotations

import uuid
from math import ceil

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_features.models.application import Application
from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.user import User, UserRole
from app.modules.application_status.models import ApplicationStatusHistory
from app.modules.application_status.schemas import (
    ApplicationStatusPage,
    ApplicationStatusPatch,
    StatusHistoryEntry,
)
from app.modules.application_status.service import ApplicationStatusService
from app.modules.jobs.service import JobsService
from app.utils.responses import success_response

router = APIRouter(tags=["Applications"])


async def _authorized_application(
    db: AsyncSession, user: User, application_id: uuid.UUID, *, require_edit: bool
):
    application = (
        await db.execute(select(Application).where(Application.id == application_id))
    ).scalar_one_or_none()
    if application is None:
        raise NotFoundException("Application not found")
    job = await JobsService.get_job(db, user, application.job_id, require_edit=require_edit)
    if job.company_id != application.company_id:
        raise NotFoundException("Application not found")
    if user.role not in {UserRole.ADMIN, UserRole.RECRUITER}:
        raise ForbiddenException("Insufficient permissions to change application status")
    return application


@router.patch(
    "/applications/{application_id}/status",
    summary="Change application status",
    description="Applies an authorized recruiter status transition and records immutable history.",
)
async def change_application_status(
    application_id: uuid.UUID,
    body: ApplicationStatusPatch,
    request_id: uuid.UUID | None = Header(default=None, alias="X-Request-ID"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    await _authorized_application(db, user, application_id, require_edit=True)
    application, history = await ApplicationStatusService.transition(
        db,
        application_id,
        body.status,
        actor_type="user",
        actor_user_id=user.id,
        reason=body.reason,
        request_id=request_id,
    )
    return success_response(
        data={
            "application": {
                "id": str(application.id),
                "job_id": str(application.job_id),
                "company_id": str(application.company_id),
                "status": application.status,
            },
            "history": StatusHistoryEntry.model_validate(history).model_dump(mode="json"),
        },
        message="Application status updated",
    )


@router.get(
    "/applications/{application_id}/status-history",
    response_model=ApplicationStatusPage,
    summary="List application status history",
    description="Returns status transitions newest first for an accessible application.",
)
async def application_status_history(
    application_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    await _authorized_application(db, user, application_id, require_edit=False)
    base_query = select(ApplicationStatusHistory).where(
        ApplicationStatusHistory.application_id == application_id
    )
    total = await db.scalar(
        select(func.count()).select_from(base_query.subquery())
    )
    rows = (
        await db.execute(
            base_query.order_by(
                ApplicationStatusHistory.created_at.desc(),
                ApplicationStatusHistory.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    total = int(total or 0)
    return {
        "items": rows,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": ceil(total / page_size) if total else 0,
    }
