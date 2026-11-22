"""Re-implementation of the documented JobsService.get_job semantics (PROJECT_GUIDE.md):
company members get full access; otherwise an explicit viewer/editor grant; no access -> not found."""

import sqlalchemy as sa
from fastapi import HTTPException

from app.models.job import Job, JobAccess


class JobsService:
    async def get_job(self, db, user, job_id, require_edit: bool = False):
        job = (await db.execute(sa.select(Job).where(Job.id == job_id))).scalar_one_or_none()
        if job is None:
            raise HTTPException(404, "Job not found")
        if user.company_id is not None and user.company_id == job.company_id:
            return job
        grant = (
            await db.execute(
                sa.select(JobAccess).where(JobAccess.job_id == job_id, JobAccess.user_id == user.id)
            )
        ).scalar_one_or_none()
        if grant is None:
            raise HTTPException(404, "Job not found")
        if require_edit and grant.access_level != "editor":
            raise HTTPException(403, "Edit access required")
        return job
