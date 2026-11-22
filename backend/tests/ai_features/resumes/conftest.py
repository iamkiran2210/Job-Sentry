from __future__ import annotations

import os

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.ai_features.models.application  # noqa: F401  (register every table on Base.metadata)
import app.ai_features.models.candidate  # noqa: F401
import app.models.company  # noqa: F401
import app.ai_features.models.extracted_profile  # noqa: F401
import app.ai_features.models.identity_suggestion  # noqa: F401
import app.models.job  # noqa: F401
import app.ai_features.models.resume  # noqa: F401
import app.models.user  # noqa: F401
from app.core.database import Base
from app.ai_features.resumes.config import ResumeSettings
from app.ai_features.resumes.storage.local import LocalStorage

DB_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///./test_resumes.db")
_jobs = sa.table("jobs", sa.column("id", sa.Uuid()), sa.column("company_id", sa.Uuid()))


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine(DB_URL)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.drop_all)
        await c.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def cfg(tmp_path):
    return ResumeSettings(
        local_storage_dir=str(tmp_path / "store"),
        tesseract_cmd=(os.environ.get("RESUMES_TESSERACT_CMD") or ResumeSettings().tesseract_cmd),
        task_max_attempts=3,
        task_retry_base_seconds=1,
        _env_file=None,
    )


@pytest.fixture
def storage(cfg):
    return LocalStorage(cfg.local_storage_dir)


class Policy:
    """Repo-agnostic stand-in for Phase 2's JobsService.get_job, implementing its documented rules:
    company member => full access; otherwise an explicit viewer/editor grant; no access => 404."""

    def __init__(self):
        self.grants: dict[tuple, str] = {}  # (user_id, job_id) -> "viewer" | "editor"


@pytest.fixture
def policy(monkeypatch):
    pol = Policy()

    async def get_accessible_job(db, user, job_id, *, require_edit=False):
        row = (
            await db.execute(sa.select(_jobs.c.id, _jobs.c.company_id).where(_jobs.c.id == job_id))
        ).first()
        if row is None:
            raise HTTPException(404, "Job not found")
        if user.company_id is not None and user.company_id == row.company_id:
            return row
        level = pol.grants.get((user.id, job_id))
        if level is None:
            raise HTTPException(404, "Job not found")
        if require_edit and level != "editor":
            raise HTTPException(403, "Edit access required")
        return row

    monkeypatch.setattr("app.ai_features.resumes.service.get_accessible_job", get_accessible_job)
    monkeypatch.setattr("app.ai_features.candidates.service.get_accessible_job", get_accessible_job)
    return pol
