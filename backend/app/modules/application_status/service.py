from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_features.models.application import Application
from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.models.user import User, UserRole
from app.modules.application_status.models import ApplicationStatusHistory


class ApplicationStatus(StrEnum):
    APPLIED = "applied"
    PROCESSING = "processing"
    ANALYZED = "analyzed"
    SHORTLISTED = "shortlisted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.APPLIED: {ApplicationStatus.PROCESSING, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.PROCESSING: {
        ApplicationStatus.ANALYZED, ApplicationStatus.APPLIED, ApplicationStatus.WITHDRAWN
    },
    ApplicationStatus.ANALYZED: {
        ApplicationStatus.SHORTLISTED, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN
    },
    ApplicationStatus.SHORTLISTED: {
        ApplicationStatus.ANALYZED, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN
    },
    ApplicationStatus.REJECTED: {ApplicationStatus.ANALYZED, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.WITHDRAWN: set(),
}

USER_STATUSES = {
    ApplicationStatus.SHORTLISTED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.WITHDRAWN,
    ApplicationStatus.ANALYZED,
}
SYSTEM_STATUSES = {ApplicationStatus.PROCESSING, ApplicationStatus.ANALYZED, ApplicationStatus.APPLIED}


class ApplicationStatusService:
    @staticmethod
    async def transition(
        db: AsyncSession,
        application_id: uuid.UUID,
        target_status: str | ApplicationStatus,
        *,
        actor_type: str,
        actor_user_id: uuid.UUID | None = None,
        reason: str | None = None,
        request_id: uuid.UUID | None = None,
    ) -> tuple[Application, ApplicationStatusHistory]:
        try:
            target = ApplicationStatus(target_status)
        except ValueError as exc:
            raise ValidationException("Unknown application status") from exc

        if actor_type not in {"user", "system"}:
            raise ValidationException("Invalid status actor")
        if actor_type == "user":
            if actor_user_id is None:
                raise ValidationException("A user actor is required")
            user = await db.get(User, actor_user_id)
            if user is None or user.role not in {UserRole.ADMIN, UserRole.RECRUITER}:
                raise NotFoundException("Application not found")
            if target not in USER_STATUSES:
                raise ConflictException("Users cannot set this application status")
        elif actor_user_id is not None:
            raise ValidationException("System actors cannot have a user id")
        elif target not in SYSTEM_STATUSES:
            raise ConflictException("System actors cannot set this application status")

        if target == ApplicationStatus.REJECTED and not (reason and reason.strip()):
            raise ValidationException("A non-empty reason is required to reject an application")
        if reason is not None and len(reason) > 1000:
            raise ValidationException("Reason must be at most 1000 characters")

        application = (
            await db.execute(
                select(Application)
                .where(Application.id == application_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if application is None:
            raise NotFoundException("Application not found")
        current = ApplicationStatus(application.status)
        if target == current or target not in TRANSITIONS[current]:
            raise ConflictException(f"Cannot change application status from {current.value} to {target.value}")

        application.status = target.value
        history = ApplicationStatusHistory(
            application_id=application.id,
            job_id=application.job_id,
            company_id=application.company_id,
            from_status=current.value,
            to_status=target.value,
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            reason=reason.strip() if reason else None,
            request_id=request_id,
        )
        db.add(history)
        await db.flush()
        return application, history

    @staticmethod
    async def set_system_status_if_needed(
        db: AsyncSession, application_id: uuid.UUID, target: ApplicationStatus
    ) -> tuple[Application, ApplicationStatusHistory | None]:
        application = (
            await db.execute(
                select(Application).where(Application.id == application_id).with_for_update()
            )
        ).scalar_one_or_none()
        if application is None:
            raise NotFoundException("Application not found")
        if application.status == target.value:
            return application, None
        return await ApplicationStatusService.transition(
            db, application_id, target, actor_type="system"
        )
