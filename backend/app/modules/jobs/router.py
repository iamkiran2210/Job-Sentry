import traceback
import uuid

from app.ai_features.ai.skill_extraction import skill_build_workflow, RecommendationSchema
from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.core.exceptions import AppException
from app.models.user import User
from app.modules.jobs.provider import get_requirement_extraction_provider
from app.modules.jobs.service import JobsService
from app.schemas.job import (
    JobCreateRequest,
    JobAccessGrantRequest,
    JobAccessResponse,
    JobRequirementCreateRequest,
    JobRequirementResponse,
    JobRequirementUpdateRequest,
    JobResponse,
    JobUpdateRequest,
    RequirementExtractionRequest,
)
from app.utils.responses import success_response
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/jobs", tags=["Jobs"])


def serialize(model, schema):
    return schema.model_validate(model).model_dump(mode="json")


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new job",
    description="Creates a draft job for the authenticated user's company.",
)
async def create_job(
        request: JobCreateRequest,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    job = await JobsService.create_job(db, current_user, request)
    return success_response(
        serialize(job, JobResponse), "Job created successfully", status.HTTP_201_CREATED
    )


@router.get(
    "",
    summary="List company jobs",
    description="Returns jobs belonging to the authenticated user's company.",
)
async def list_jobs(
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    jobs = await JobsService.list_jobs(db, current_user)
    return success_response(
        [serialize(job, JobResponse) for job in jobs], "Jobs retrieved successfully"
    )


@router.get(
    "/{job_id}",
    summary="Get a job",
    description="Returns a job belonging to the authenticated user's company.",
)
async def get_job(
        job_id: uuid.UUID,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    job = await JobsService.get_job(db, current_user, job_id)
    return success_response(serialize(job, JobResponse), "Job retrieved successfully")


@router.put(
    "/{job_id}",
    summary="Update a job",
    description="Updates an editable job belonging to the authenticated user's company.",
)
async def update_job(
        job_id: uuid.UUID,
        request: JobUpdateRequest,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    job = await JobsService.update_job(db, current_user, job_id, request)
    return success_response(serialize(job, JobResponse), "Job updated successfully")


@router.delete(
    "",
    status_code=status.HTTP_200_OK,
    summary="Delete all company jobs (Data Explorer)",
    description="Permanently deletes all jobs and associated applications, resumes, scores, and history for the authenticated user's company.",
)
async def delete_all_jobs(
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    counts = await JobsService.purge_all_jobs(db, current_user)
    return success_response(counts, "All company jobs deleted successfully")


@router.delete(
    "/{job_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a job",
    description=(
            "Deletes a draft job belonging to the authenticated user's company. "
            "Pass ?purge=true to clean-delete a job of any status along with all associated "
            "applications, resumes, scores, verifications, and history."
    ),
)
async def delete_job(
        job_id: uuid.UUID,
        purge: bool = Query(
            False,
            description="Clean-delete the job (any status) and all associated records/files.",
        ),
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    if purge:
        counts = await JobsService.purge_job(db, current_user, job_id)
        return success_response(
            {"deleted": True, "clean_deleted": True, **counts},
            "Job and all associated data permanently deleted",
        )
    await JobsService.delete_job(db, current_user, job_id)
    return success_response(None, "Draft job deleted successfully")


async def change_status(action, job_id, current_user, db):
    job = await JobsService.transition(db, current_user, job_id, action)
    messages = {
        "publish": "published",
        "pause": "paused",
        "close": "closed",
        "archive": "archived",
    }
    return success_response(serialize(job, JobResponse), f"Job {messages[action]} successfully")


@router.post(
    "/{job_id}/publish",
    summary="Publish a job",
    description="Publishes a draft job or resumes a paused job after validating preference weights.",
)
async def publish_job(
        job_id: uuid.UUID,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    return await change_status("publish", job_id, current_user, db)


@router.post(
    "/{job_id}/pause",
    summary="Pause a job",
    description="Pauses an active job belonging to the authenticated user's company.",
)
async def pause_job(
        job_id: uuid.UUID,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    return await change_status("pause", job_id, current_user, db)


@router.post(
    "/{job_id}/close",
    summary="Close a job",
    description="Closes an active or paused job belonging to the authenticated user's company.",
)
async def close_job(
        job_id: uuid.UUID,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    return await change_status("close", job_id, current_user, db)


@router.post(
    "/{job_id}/archive",
    summary="Archive a job",
    description="Archives a closed job belonging to the authenticated user's company.",
)
async def archive_job(
        job_id: uuid.UUID,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    return await change_status("archive", job_id, current_user, db)


async def owned_job(job_id, current_user, db, require_edit=False):
    return await JobsService.get_job(db, current_user, job_id, require_edit=require_edit)


@router.get(
    "/{job_id}/requirements",
    summary="List job requirements",
    description="Returns structured requirements for a job in the authenticated user's company.",
)
async def list_requirements(
        job_id: uuid.UUID,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    job = await owned_job(job_id, current_user, db)
    requirements = await JobsService.list_requirements(db, job)
    return success_response(
        [serialize(item, JobRequirementResponse) for item in requirements],
        "Requirements retrieved successfully",
    )


@router.post(
    "/{job_id}/requirements",
    status_code=status.HTTP_201_CREATED,
    summary="Create a job requirement",
    description="Adds a validated mandatory or preferred requirement to a company job.",
)
async def create_requirement(
        job_id: uuid.UUID,
        request: JobRequirementCreateRequest,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    job = await owned_job(job_id, current_user, db, require_edit=True)
    requirement = await JobsService.create_requirement(db, job, request)
    return success_response(
        serialize(requirement, JobRequirementResponse),
        "Requirement created successfully",
        status.HTTP_201_CREATED,
    )


@router.put(
    "/{job_id}/requirements/{requirement_id}",
    summary="Update a job requirement",
    description="Updates a requirement belonging to a job in the authenticated user's company.",
)
async def update_requirement(
        job_id: uuid.UUID,
        requirement_id: uuid.UUID,
        request: JobRequirementUpdateRequest,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    job = await owned_job(job_id, current_user, db, require_edit=True)
    requirement = await JobsService.update_requirement(db, job, requirement_id, request)
    return success_response(
        serialize(requirement, JobRequirementResponse),
        "Requirement updated successfully",
    )


@router.delete(
    "/{job_id}/requirements/{requirement_id}",
    summary="Delete a job requirement",
    description="Deletes a requirement belonging to a job in the authenticated user's company.",
)
async def delete_requirement(
        job_id: uuid.UUID,
        requirement_id: uuid.UUID,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    job = await owned_job(job_id, current_user, db, require_edit=True)
    await JobsService.delete_requirement(db, job, requirement_id)
    return success_response(None, "Requirement deleted successfully")


@router.post(
    "/{job_id}/extract-requirements",
    summary="Extract requirement suggestions",
    description="Returns validated AI-assisted suggestions for recruiter review without saving them.",
)
async def extract_requirements(
        job_id: uuid.UUID,
        request: RequirementExtractionRequest,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
        provider=Depends(get_requirement_extraction_provider),
):
    job = await owned_job(job_id, current_user, db)
    description = request.description or job.description
    if provider is None:
        raise AppException("Requirement extraction provider is not configured", status_code=503)
    try:
        if type(provider).__name__ not in {"_Provider", "AIRequirementProvider"}:
            raw = await provider.extract_requirements(description)
            if isinstance(raw, dict) and "requirements" in raw and "suggestions" not in raw:
                raw = {**raw, "suggestions": raw["requirements"]}
            validated = await JobsService.validate_extraction(raw)
            return success_response(
                validated.model_dump(mode="json"),
                "Requirement suggestions generated for recruiter review",
            )
        output = await skill_build_workflow.run_async(description)
        suggestions = RecommendationSchema.model_validate(output)
    except AppException:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise AppException(
            "Requirement extraction provider returned invalid output", status_code=502
        ) from exc
    return success_response(
        suggestions.model_dump(mode="json"),
        "Requirement suggestions generated for recruiter review",
    )


def serialize_job_access(record: tuple):
    grant, user = record
    return JobAccessResponse(
        user_id=user.id,
        name=user.name,
        email=user.email,
        access_level=grant.access_level,
        granted_by_id=grant.granted_by_id,
        created_at=grant.created_at,
    ).model_dump(mode="json")


@router.get(
    "/{job_id}/access",
    summary="List job access grants",
    description="Lists users granted access to a job. Restricted to the job's company administrators.",
)
async def list_job_access(
        job_id: uuid.UUID,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    job = await owned_job(job_id, current_user, db)
    grants = await JobsService.list_job_access(db, current_user, job)
    return success_response(
        [serialize_job_access(grant) for grant in grants],
        "Job access retrieved successfully",
    )


@router.post(
    "/{job_id}/access",
    status_code=status.HTTP_201_CREATED,
    summary="Grant job access",
    description="Grants a registered user viewer or editor access to this job.",
)
async def grant_job_access(
        job_id: uuid.UUID,
        request: JobAccessGrantRequest,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    job = await owned_job(job_id, current_user, db)
    grant = await JobsService.grant_job_access(db, current_user, job, request)
    return success_response(
        serialize_job_access(grant),
        "Job access granted successfully",
        status.HTTP_201_CREATED,
    )


@router.delete(
    "/{job_id}/access/{user_id}",
    summary="Revoke job access",
    description="Revokes an explicit access grant to this job.",
)
async def revoke_job_access(
        job_id: uuid.UUID,
        user_id: uuid.UUID,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
):
    job = await owned_job(job_id, current_user, db)
    await JobsService.revoke_job_access(db, current_user, job, user_id)
    return success_response(None, "Job access revoked successfully")
