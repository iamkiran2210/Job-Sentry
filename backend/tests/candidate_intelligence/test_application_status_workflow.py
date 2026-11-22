from __future__ import annotations

import asyncio
import uuid

import pytest
from app.ai_features.models.application import Application
from app.ai_features.models.resume import Resume
from app.ai_features.resumes.config import ResumeSettings
from app.ai_features.resumes.errors import FailureCode
from app.ai_features.resumes.pipeline import Claim, _claim, _fail, _finalize
from app.ai_features.schemas.resume_extraction import ExtractedProfileData
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app as fastapi_app
from app.models.company import Company
from app.models.job import EmploymentType, Job, WorkMode
from app.models.job_access import JobAccess, JobAccessLevel
from app.models.user import User, UserRole
from app.modules.application_status.models import ApplicationStatusHistory
from app.modules.application_status.service import ApplicationStatusService
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker


async def seed_application(engine, status="applied", role=UserRole.RECRUITER):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        company = Company(name=f"status-{uuid.uuid4()}")
        user = User(
            name="Status Recruiter",
            email=f"{uuid.uuid4()}@example.test",
            company=company,
            role=role,
        )
        job = Job(
            company=company,
            title="Backend",
            description="Backend role",
            employment_type=EmploymentType.FULL_TIME,
            work_mode=WorkMode.REMOTE,
        )
        session.add_all([company, user, job])
        await session.flush()
        application = Application(company_id=company.id, job_id=job.id, status=status)
        session.add(application)
        await session.commit()
        return application.id, job.id, company.id, user.id


async def seed_resume(engine, application_id, job_id, company_id, status="uploaded"):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        resume = Resume(
            company_id=company_id,
            job_id=job_id,
            application_id=application_id,
            original_filename="candidate.pdf",
            extension="pdf",
            content_type="application/pdf",
            size_bytes=100,
            sha256=uuid.uuid4().hex,
            storage_backend="local",
            storage_key=uuid.uuid4().hex,
            status=status,
        )
        session.add(resume)
        await session.commit()
        return resume.id


ALLOWED = [
    ("applied", "processing", "system"),
    ("applied", "withdrawn", "user"),
    ("processing", "analyzed", "system"),
    ("processing", "applied", "system"),
    ("processing", "withdrawn", "user"),
    ("analyzed", "shortlisted", "user"),
    ("analyzed", "rejected", "user"),
    ("analyzed", "withdrawn", "user"),
    ("shortlisted", "analyzed", "user"),
    ("shortlisted", "rejected", "user"),
    ("shortlisted", "withdrawn", "user"),
    ("rejected", "analyzed", "user"),
    ("rejected", "withdrawn", "user"),
]


@pytest.mark.integration
@pytest.mark.requires_pgvector
@pytest.mark.parametrize(("source", "target", "actor_type"), ALLOWED)
async def test_allowed_status_transitions_write_history(alembic_db, source, target, actor_type):
    application_id, _, _, user_id = await seed_application(alembic_db, source)
    sessions = async_sessionmaker(alembic_db, expire_on_commit=False)
    async with sessions() as session:
        application, history = await ApplicationStatusService.transition(
            session,
            application_id,
            target,
            actor_type=actor_type,
            actor_user_id=user_id if actor_type == "user" else None,
            reason="Human decision" if target == "rejected" else None,
        )
        assert application.status == target
        assert history.from_status == source
        assert history.to_status == target
        assert history.actor_type == actor_type
        assert history.actor_user_id == (user_id if actor_type == "user" else None)


@pytest.mark.integration
@pytest.mark.requires_pgvector
@pytest.mark.parametrize(
    "source", ["applied", "processing", "analyzed", "shortlisted", "rejected", "withdrawn"]
)
async def test_same_status_is_rejected(alembic_db, source):
    from app.core.exceptions import ConflictException

    application_id, _, _, user_id = await seed_application(alembic_db, source)
    sessions = async_sessionmaker(alembic_db, expire_on_commit=False)
    async with sessions() as session:
        with pytest.raises(ConflictException):
            await ApplicationStatusService.transition(
                session,
                application_id,
                source,
                actor_type="user",
                actor_user_id=user_id,
                reason="Reason required to test this rejected status",
            )


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_rejection_requires_reason_and_system_cannot_reject(alembic_db):
    from app.core.exceptions import ValidationException, ConflictException

    application_id, _, _, user_id = await seed_application(alembic_db, "analyzed")
    sessions = async_sessionmaker(alembic_db, expire_on_commit=False)
    async with sessions() as session:
        with pytest.raises(ValidationException):
            await ApplicationStatusService.transition(
                session, application_id, "rejected", actor_type="user", actor_user_id=user_id
            )
        with pytest.raises(ConflictException):
            await ApplicationStatusService.transition(
                session, application_id, "rejected", actor_type="system", reason="not allowed"
            )
        with pytest.raises(ValidationException):
            await ApplicationStatusService.transition(
                session,
                application_id,
                "rejected",
                actor_type="user",
                actor_user_id=user_id,
                reason=" " * 2,
            )
        with pytest.raises(ValidationException):
            await ApplicationStatusService.transition(
                session,
                application_id,
                "rejected",
                actor_type="user",
                actor_user_id=user_id,
                reason="x" * 1001,
            )


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_withdrawn_is_terminal_and_disallowed_edges_reject(alembic_db):
    from app.core.exceptions import ConflictException

    for source, targets in {
        "applied": ["analyzed", "shortlisted", "rejected"],
        "processing": ["shortlisted", "rejected"],
        "analyzed": ["processing", "applied"],
        "shortlisted": ["processing", "applied"],
        "rejected": ["processing", "shortlisted", "applied"],
        "withdrawn": ["applied", "processing", "analyzed", "shortlisted", "rejected"],
    }.items():
        for target in targets:
            application_id, _, _, user_id = await seed_application(alembic_db, source)
            sessions = async_sessionmaker(alembic_db, expire_on_commit=False)
            async with sessions() as session:
                with pytest.raises(ConflictException):
                    await ApplicationStatusService.transition(
                        session,
                        application_id,
                        target,
                        actor_type="user",
                        actor_user_id=user_id,
                        reason="Reason required to test this rejected status",
                    )


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_status_change_rolls_back_with_history(alembic_db):
    application_id, _, _, user_id = await seed_application(alembic_db)
    sessions = async_sessionmaker(alembic_db, expire_on_commit=False)
    async with sessions() as session:
        await ApplicationStatusService.transition(
            session, application_id, "withdrawn", actor_type="user", actor_user_id=user_id
        )
        await session.rollback()
    async with sessions() as session:
        application = await session.get(Application, application_id)
        history = (
            (
                await session.execute(
                    select(ApplicationStatusHistory).where(
                        ApplicationStatusHistory.application_id == application_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert application.status == "applied"
        assert history == []


@pytest.mark.integration
@pytest.mark.requires_pgvector
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
async def test_status_history_is_append_only(alembic_db, operation):
    application_id, _, _, user_id = await seed_application(alembic_db)
    sessions = async_sessionmaker(alembic_db, expire_on_commit=False)
    async with sessions() as session:
        _, history = await ApplicationStatusService.transition(
            session, application_id, "withdrawn", actor_type="user", actor_user_id=user_id
        )
        await session.commit()
        statement = (
            "UPDATE job_sentry.application_status_history SET reason = 'changed' WHERE id = :id"
            if operation == "UPDATE"
            else "DELETE FROM job_sentry.application_status_history WHERE id = :id"
        )
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(text(statement), {"id": history.id})
        await session.rollback()


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_concurrent_status_patch_has_one_winner_and_one_conflict(alembic_db):
    from app.core.exceptions import ConflictException

    application_id, _, _, user_id = await seed_application(alembic_db)
    sessions = async_sessionmaker(alembic_db, expire_on_commit=False)
    first, second = sessions(), sessions()
    try:
        await ApplicationStatusService.transition(
            first, application_id, "withdrawn", actor_type="user", actor_user_id=user_id
        )
        pending = asyncio.create_task(
            ApplicationStatusService.transition(
                second, application_id, "withdrawn", actor_type="user", actor_user_id=user_id
            )
        )
        await asyncio.sleep(0.1)
        assert pending.done() is False
        await first.commit()
        with pytest.raises(ConflictException):
            await asyncio.wait_for(pending, timeout=5)
        count = await second.scalar(
            select(func.count())
            .select_from(ApplicationStatusHistory)
            .where(ApplicationStatusHistory.application_id == application_id)
        )
        assert count == 1
    finally:
        await first.close()
        await second.close()


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_status_patch_authorization_tenant_scope_and_history_page(alembic_db):
    application_id, job_id, company_id, user_id = await seed_application(alembic_db, "analyzed")
    sessions = async_sessionmaker(alembic_db, expire_on_commit=False)

    async def override_db():
        async with sessions() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = override_db
    try:
        async with sessions() as session:
            owner = await session.get(User, user_id)
            stranger_company = Company(name=f"other-{uuid.uuid4()}")
            viewer = User(
                name="Viewer", email=f"{uuid.uuid4()}@example.test", company=stranger_company
            )
            session.add_all([stranger_company, viewer])
            await session.flush()
            session.add(
                JobAccess(
                    job_id=job_id,
                    user_id=viewer.id,
                    granted_by_id=user_id,
                    access_level=JobAccessLevel.VIEWER,
                )
            )
            await session.commit()
            owner_token = create_access_token(str(user_id), owner.role.value, str(company_id))
            viewer_token = create_access_token(
                str(viewer.id), viewer.role.value, str(stranger_company.id)
            )

        transport = ASGITransport(app=fastapi_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            request_id = uuid.uuid4()
            changed = await client.patch(
                f"/api/v1/applications/{application_id}/status",
                headers={"Authorization": f"Bearer {owner_token}", "X-Request-ID": str(request_id)},
                json={"status": "shortlisted"},
            )
            assert changed.status_code == 200
            assert changed.json()["data"]["application"]["status"] == "shortlisted"
            assert changed.json()["data"]["history"]["request_id"] == str(request_id)

            missing_reason = await client.patch(
                f"/api/v1/applications/{application_id}/status",
                headers={"Authorization": f"Bearer {owner_token}"},
                json={"status": "rejected"},
            )
            assert missing_reason.status_code == 422
            extra_field = await client.patch(
                f"/api/v1/applications/{application_id}/status",
                headers={"Authorization": f"Bearer {owner_token}"},
                json={"status": "withdrawn", "unexpected": True},
            )
            assert extra_field.status_code == 422

            history = await client.get(
                f"/api/v1/applications/{application_id}/status-history?page=1&page_size=1",
                headers={"Authorization": f"Bearer {owner_token}"},
            )
            assert history.status_code == 200
            assert history.json()["items"][0]["to_status"] == "shortlisted"
            assert history.json()["total"] == 1

            forbidden = await client.patch(
                f"/api/v1/applications/{application_id}/status",
                headers={"Authorization": f"Bearer {viewer_token}"},
                json={"status": "withdrawn"},
            )
            assert forbidden.status_code == 403

            missing = await client.patch(
                f"/api/v1/applications/{uuid.uuid4()}/status",
                headers={"Authorization": f"Bearer {viewer_token}"},
                json={"status": "withdrawn"},
            )
            assert missing.status_code == 404

            async with sessions() as session:
                outsider_company = Company(name=f"outsider-{uuid.uuid4()}")
                outsider = User(
                    name="Outsider", email=f"{uuid.uuid4()}@example.test", company=outsider_company
                )
                session.add_all([outsider_company, outsider])
                await session.commit()
                outsider_token = create_access_token(
                    str(outsider.id), outsider.role.value, str(outsider_company.id)
                )
            isolated = await client.get(
                f"/api/v1/applications/{application_id}/status-history",
                headers={"Authorization": f"Bearer {outsider_token}"},
            )
            assert isolated.status_code == 404
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_worker_records_processing_and_resets_to_applied_on_failure(alembic_db):
    application_id, job_id, company_id, _ = await seed_application(alembic_db)
    resume_id = await seed_resume(alembic_db, application_id, job_id, company_id)
    sessions = async_sessionmaker(alembic_db, expire_on_commit=False)

    async with sessions() as session:
        claim = await _claim(session, resume_id, ResumeSettings(lease_seconds=30))
        assert claim is not None
        await session.commit()
    assert claim is not None
    await _fail(sessions, resume_id, FailureCode.INTERNAL_ERROR)

    async with sessions() as session:
        application = await session.get(Application, application_id)
        rows = (
            (
                await session.execute(
                    select(ApplicationStatusHistory)
                    .where(ApplicationStatusHistory.application_id == application_id)
                    .order_by(ApplicationStatusHistory.created_at)
                )
            )
            .scalars()
            .all()
        )
        assert application.status == "applied"
        assert [(row.from_status, row.to_status, row.actor_type) for row in rows] == [
            ("applied", "processing", "system"),
            ("processing", "applied", "system"),
        ]


@pytest.mark.integration
@pytest.mark.requires_pgvector
async def test_worker_marks_application_analyzed_on_success(alembic_db):
    application_id, job_id, company_id, _ = await seed_application(alembic_db, "processing")
    resume_id = await seed_resume(alembic_db, application_id, job_id, company_id, "analyzing")
    claim = Claim(
        resume_id=resume_id,
        company_id=company_id,
        job_id=job_id,
        application_id=application_id,
        storage_key="key",
        sha256="a" * 64,
        content_type="application/pdf",
        attempt=1,
    )
    sessions = async_sessionmaker(alembic_db, expire_on_commit=False)
    async with sessions() as session:
        await _finalize(session, claim, ExtractedProfileData())
        await session.commit()
    async with sessions() as session:
        application = await session.get(Application, application_id)
        row = (
            await session.execute(
                select(ApplicationStatusHistory).where(
                    ApplicationStatusHistory.application_id == application_id,
                    ApplicationStatusHistory.to_status == "analyzed",
                )
            )
        ).scalar_one()
        assert application.status == "analyzed"
        assert row.actor_type == "system"
