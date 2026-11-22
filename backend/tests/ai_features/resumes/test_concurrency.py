"""Race conditions. Need real row locks => PostgreSQL only (set TEST_DATABASE_URL to a postgresql+asyncpg URL)."""

import asyncio

import pytest
import sqlalchemy as sa

from app.ai_features.resumes import pipeline
from app.ai_features.models.application import Application
from app.ai_features.models.candidate import Candidate
from app.ai_features.models.resume import Resume

from . import fixtures as fx
from .conftest import DB_URL
from .helpers import FakeLLM, count, make_company, make_job, row, run, upload

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not DB_URL.startswith("postgresql"), reason="needs PostgreSQL"),
]


async def test_duplicate_delivery_runs_pipeline_once(factory, cfg, storage):
    company = await make_company(factory)
    job = await make_job(factory, company)
    res = await upload(factory, cfg, storage, company, job, fx.make_pdf())
    llm = FakeLLM(fx.profile_dict())
    outs = await asyncio.gather(*[run(factory, cfg, storage, llm, res.resume_id) for _ in range(4)])
    assert sorted(o.kind for o in outs) == [
        "completed",
        "skipped",
        "skipped",
        "skipped",
    ]
    assert (
            llm.calls == 1
            and await count(factory, Candidate) == 1
            and await count(factory, Application) == 1
    )


async def test_concurrent_identical_uploads_create_one_resume(factory, cfg, storage):
    company = await make_company(factory)
    job = await make_job(factory, company)
    data = fx.make_pdf()
    results = await asyncio.gather(
        *[upload(factory, cfg, storage, company, job, data) for _ in range(5)]
    )
    assert sorted(r.status for r in results).count("accepted") == 1
    assert {r.resume_id for r in results if r.resume_id} == {
        next(r.resume_id for r in results if r.status == "accepted")
    }
    assert await count(factory, Resume) == 1 and await count(factory, Application) == 1


async def test_same_person_processed_concurrently_gets_one_candidate(
        factory, cfg, storage, monkeypatch
):
    # Hold every worker inside the identity critical section so the race is deterministic:
    # without the advisory lock all four would look up "no candidate yet" and each create one.
    original = pipeline._identity_lock

    async def slow(session, company_id, key):
        await original(session, company_id, key)
        await session.execute(sa.text("select pg_sleep(0.3)"))

    monkeypatch.setattr(pipeline, "_identity_lock", slow)
    company = await make_company(factory)
    jobs = [await make_job(factory, company) for _ in range(4)]
    ups = [await upload(factory, cfg, storage, company, j, fx.make_pdf()) for j in jobs]
    llm = FakeLLM(fx.profile_dict())
    outs = await asyncio.gather(*[run(factory, cfg, storage, llm, u.resume_id) for u in ups])
    assert all(o.kind == "completed" for o in outs)
    assert await count(factory, Candidate) == 1 and await count(factory, Application) == 4
