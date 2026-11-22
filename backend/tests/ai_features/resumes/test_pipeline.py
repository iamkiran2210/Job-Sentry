import datetime as dt

import pytest
import sqlalchemy as sa

from types import SimpleNamespace

from app.ai_features.resumes import service
from app.ai_features.resumes.errors import FailureCode, PipelineError
from app.ai_features.resumes.service import NotFound, ResumesService, RetryConflict
from app.ai_features.resumes.timeutil import utcnow
from app.ai_features.models.application import Application
from app.ai_features.models.candidate import Candidate
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.identity_suggestion import IdentitySuggestion
from app.ai_features.models.resume import Resume

from . import fixtures as fx
from .helpers import (
    FakeLLM,
    RecordingDispatcher,
    count,
    make_company,
    make_job,
    row,
    run,
    upload,
)

pytestmark = pytest.mark.asyncio


async def setup(factory, cfg, storage, data=None, name="cv.pdf", company=None, job=None):
    company = company or await make_company(factory)
    job = job or await make_job(factory, company)
    res = await upload(factory, cfg, storage, company, job, data or fx.make_pdf(), name)
    assert res.status == "accepted"
    return company, job, res


async def test_happy_path(factory, cfg, storage):
    company, job, res = await setup(factory, cfg, storage)
    llm = FakeLLM(fx.profile_dict())
    out = await run(factory, cfg, storage, llm, res.resume_id)
    assert out.kind == "completed" and llm.calls == 1
    r = await row(factory, Resume, res.resume_id)
    assert (
            r.status == "completed"
            and r.completed_at
            and r.lease_expires_at is None
            and r.failure_code is None
    )
    async with factory() as s:
        p = (await s.execute(sa.select(ExtractedProfile))).scalar_one()
        app = await s.get(Application, res.application_id)
        cand = await s.get(Candidate, app.candidate_id)
    assert (
            p.extraction_method == "pdf_text"
            and p.profile_data["contact"]["email"]["value"] == "jane.example@example.com"
    )
    assert (
            p.overall_confidence
            and p.ai_model == "fake-1"
            and p.ai_engine == "fake"
            and p.prompt_version == "test-v1"
            and p.schema_version == 1
    )
    assert (
            app.status == "analyzed"
            and cand.normalized_email == "jane.example@example.com"
            and cand.company_id == company
    )


async def test_reprocessing_is_idempotent(factory, cfg, storage):
    _, _, res = await setup(factory, cfg, storage)
    llm = FakeLLM(fx.profile_dict())
    await run(factory, cfg, storage, llm, res.resume_id)
    for _ in range(3):
        assert (await run(factory, cfg, storage, llm, res.resume_id)).kind == "skipped"
    assert llm.calls == 1
    assert await count(factory, Candidate) == 1 and await count(factory, Application) == 1
    assert await count(factory, ExtractedProfile) == 1


async def test_transient_failure_retries_and_resumes_without_redoing_parsing(factory, cfg, storage):
    _, _, res = await setup(factory, cfg, storage)
    llm = FakeLLM(PipelineError(FailureCode.LLM_UNAVAILABLE, retryable=True), fx.profile_dict())
    out = await run(factory, cfg, storage, llm, res.resume_id)
    assert out.kind == "retry" and out.retry_in and out.code == FailureCode.LLM_UNAVAILABLE
    r = await row(factory, Resume, res.resume_id)
    assert (
            r.status == "analyzing"
            and r.lease_expires_at is None
            and r.last_error_code == "LLM_UNAVAILABLE"
    )
    r_key = r.storage_key
    storage.delete(
        r_key
    )  # prove the retry reuses cached text instead of re-reading/re-parsing the file
    assert (await run(factory, cfg, storage, llm, res.resume_id)).kind == "completed"
    assert await count(factory, Candidate) == 1 and await count(factory, Application) == 1


async def test_retries_exhausted_marks_failed_with_safe_reason(factory, cfg, storage):
    _, _, res = await setup(factory, cfg, storage)
    llm = FakeLLM(PipelineError(FailureCode.LLM_UNAVAILABLE, retryable=True))
    kinds = [
        (await run(factory, cfg, storage, llm, res.resume_id)).kind
        for _ in range(cfg.task_max_attempts)
    ]
    assert kinds == ["retry", "retry", "failed"]
    r = await row(factory, Resume, res.resume_id)
    assert r.status == "failed" and r.failure_code == "LLM_UNAVAILABLE" and r.attempt_count == 3
    assert r.failure_message == "The analysis service was temporarily unavailable."
    assert (
               await run(factory, cfg, storage, llm, res.resume_id)
           ).kind == "skipped"  # failed is terminal until manual retry


async def test_permanent_error_fails_immediately(factory, cfg, storage):
    _, _, res = await setup(factory, cfg, storage)
    out = await run(
        factory,
        cfg,
        storage,
        FakeLLM(PipelineError(FailureCode.LLM_NOT_CONFIGURED)),
        res.resume_id,
    )
    assert out.kind == "failed" and (await row(factory, Resume, res.resume_id)).attempt_count == 1


async def test_invalid_llm_output_never_stored(factory, cfg, storage):
    _, _, res = await setup(factory, cfg, storage)
    bad = {"contact": {"email": ["not", "an", "object"]}}
    llm = FakeLLM(bad)
    for _ in range(cfg.task_max_attempts):
        await run(factory, cfg, storage, llm, res.resume_id)
    r = await row(factory, Resume, res.resume_id)
    assert r.status == "failed" and r.failure_code == "LLM_INVALID_OUTPUT"
    async with factory() as s:
        assert (await s.execute(sa.select(ExtractedProfile.profile_data))).scalar_one() is None
    assert await count(factory, Candidate) == 0


async def test_unexpected_exception_text_never_leaks(factory, cfg, storage):
    _, _, res = await setup(factory, cfg, storage)
    llm = FakeLLM(RuntimeError("boom: jane.example@example.com SECRET-RESUME-TEXT"))
    for _ in range(cfg.task_max_attempts):
        await run(factory, cfg, storage, llm, res.resume_id)
    r = await row(factory, Resume, res.resume_id)
    assert r.failure_code == "INTERNAL_ERROR"
    assert "SECRET" not in (r.failure_message or "") and "jane" not in (r.failure_message or "")


async def test_corrupt_file_fails_with_code(factory, cfg, storage):
    company = await make_company(factory)
    job = await make_job(factory, company)
    data = fx.make_docx()
    res = await upload(factory, cfg, storage, company, job, data, "cv.docx")
    r = await row(factory, Resume, res.resume_id)
    import hashlib

    bad = b"PK\x03\x04 corrupt"  # valid upload, but replace blob AND hash to simulate bad-but-stored file
    storage.put(r.storage_key, bad, content_type="x")
    async with factory() as s, s.begin():
        (await s.get(Resume, r.id)).sha256 = hashlib.sha256(bad).hexdigest()
    out = await run(factory, cfg, storage, FakeLLM(fx.profile_dict()), r.id)
    assert out.kind == "failed" and out.code == FailureCode.CORRUPT_FILE


async def test_tampered_blob_fails_integrity_check(factory, cfg, storage):
    _, _, res = await setup(factory, cfg, storage)
    r = await row(factory, Resume, res.resume_id)
    storage.put(
        r.storage_key,
        fx.make_pdf(["tampered content that is long enough to be text"]),
        content_type="x",
    )
    out = await run(factory, cfg, storage, FakeLLM(fx.profile_dict()), res.resume_id)
    assert out.code == FailureCode.INTEGRITY_ERROR


async def test_missing_blob_fails(factory, cfg, storage):
    _, _, res = await setup(factory, cfg, storage)
    storage.delete((await row(factory, Resume, res.resume_id)).storage_key)
    assert (
               await run(factory, cfg, storage, FakeLLM(fx.profile_dict()), res.resume_id)
           ).code == FailureCode.STORAGE_ERROR


async def test_active_lease_prevents_concurrent_processing(factory, cfg, storage):
    _, _, res = await setup(factory, cfg, storage)
    async with factory() as s, s.begin():
        (await s.get(Resume, res.resume_id)).lease_expires_at = utcnow() + dt.timedelta(minutes=5)
    llm = FakeLLM(fx.profile_dict())
    assert (
               await run(factory, cfg, storage, llm, res.resume_id)
           ).kind == "skipped" and llm.calls == 0
    async with (
        factory() as s,
        s.begin(),
    ):  # expired lease (crashed worker) can be taken over
        (await s.get(Resume, res.resume_id)).lease_expires_at = utcnow() - dt.timedelta(minutes=1)
    assert (await run(factory, cfg, storage, llm, res.resume_id)).kind == "completed"


async def test_fabricated_llm_values_are_removed_before_storage(factory, cfg, storage):
    _, _, res = await setup(factory, cfg, storage)
    d = fx.profile_dict()
    d["contact"]["email"]["value"] = "invented@nowhere.io"
    d["skills"].append({"name": "Haskell"})
    await run(factory, cfg, storage, FakeLLM(d), res.resume_id)
    async with factory() as s:
        p = (await s.execute(sa.select(ExtractedProfile))).scalar_one()
        cand = (await s.execute(sa.select(Candidate))).scalar_one()
    assert p.profile_data["contact"]["email"]["value"] is None and cand.email is None
    assert "Haskell" not in [x["name"] for x in p.profile_data["skills"]]
    assert any("email" in w for w in p.extraction_warnings)


async def test_manual_retry_after_failure(factory, cfg, storage, policy):
    company, job, res = await setup(factory, cfg, storage)
    user = SimpleNamespace(id=None, company_id=company)
    llm = FakeLLM(PipelineError(FailureCode.LLM_NOT_CONFIGURED), fx.profile_dict())
    await run(factory, cfg, storage, llm, res.resume_id)
    disp = RecordingDispatcher()
    async with factory() as s:
        r = await ResumesService.request_retry(s, user, res.resume_id, cfg, disp)
    assert (
            r.status == "queued"
            and r.attempt_count == 0
            and r.failure_code is None
            and r.retry_count == 1
    )
    assert disp.ids == [res.resume_id]
    assert (await run(factory, cfg, storage, llm, res.resume_id)).kind == "completed"
    assert await count(factory, Application) == 1 and await count(factory, Candidate) == 1
    async with factory() as s:
        with pytest.raises(RetryConflict):  # completed is not retryable
            await ResumesService.request_retry(s, user, res.resume_id, cfg, disp)


async def test_manual_retry_limit_and_wrong_company(factory, cfg, storage, policy):
    company, job, res = await setup(factory, cfg, storage)
    other = await make_company(factory, "Other")
    async with factory() as s:
        with pytest.raises(Exception) as e:  # other company's member: no access to this job
            await ResumesService.request_retry(
                s,
                SimpleNamespace(id=None, company_id=other),
                res.resume_id,
                cfg,
                RecordingDispatcher(),
            )
    assert getattr(e.value, "status_code", None) == 404
    async with factory() as s, s.begin():
        r = await s.get(Resume, res.resume_id)
        r.status, r.retry_count = "failed", cfg.manual_retry_limit
    async with factory() as s:
        with pytest.raises(RetryConflict) as e:
            await ResumesService.request_retry(
                s,
                SimpleNamespace(id=None, company_id=company),
                res.resume_id,
                cfg,
                RecordingDispatcher(),
            )
    assert e.value.reason == "retry_limit_reached"


# ---------------------------------------------------------------- identity / duplicates
async def test_same_candidate_applies_to_two_jobs(factory, cfg, storage):
    company = await make_company(factory)
    j1, j2 = await make_job(factory, company), await make_job(factory, company)
    llm = FakeLLM(fx.profile_dict())
    same = fx.make_pdf()
    a = await upload(factory, cfg, storage, company, j1, same)
    b = await upload(factory, cfg, storage, company, j2, same)  # identical bytes, other job
    assert b.status == "accepted"
    assert (await row(factory, Resume, b.resume_id)).duplicate_of_resume_id == a.resume_id
    await run(factory, cfg, storage, llm, a.resume_id)
    await run(factory, cfg, storage, llm, b.resume_id)
    assert await count(factory, Candidate) == 1 and await count(factory, Application) == 2
    async with factory() as s:
        ids = (await s.execute(sa.select(Application.candidate_id))).scalars().all()
    assert ids[0] == ids[1]
    assert await count(factory, IdentitySuggestion) == 0


async def test_same_person_same_job_new_file_not_merged(factory, cfg, storage):
    company = await make_company(factory)
    job = await make_job(factory, company)
    llm = FakeLLM(fx.profile_dict())
    a = await upload(factory, cfg, storage, company, job, fx.make_pdf())
    b = await upload(
        factory,
        cfg,
        storage,
        company,
        job,
        fx.make_pdf(fx.RESUME_LINES + ["Updated 2026"]),
    )
    await run(factory, cfg, storage, llm, a.resume_id)
    await run(factory, cfg, storage, llm, b.resume_id)
    assert (
            await count(factory, Candidate) == 2 and await count(factory, Application) == 2
    )  # no duplicate application merge
    async with factory() as s:
        sug = (await s.execute(sa.select(IdentitySuggestion))).scalar_one()
    assert (
            sug.strength == "strong"
            and "same_job_resubmission" in sug.reasons
            and sug.status == "pending"
    )


async def test_uncertain_identity_is_flagged_not_merged(factory, cfg, storage):
    company = await make_company(factory)
    job = await make_job(factory, company)
    a = await upload(factory, cfg, storage, company, job, fx.make_pdf())
    d2 = fx.profile_dict()  # same phone, different email, different name
    lines2 = [
        "Janet Other",
        "janet@elsewhere.org | +1 415 555 0134",
        "Python developer with enough text to parse",
    ]
    b = await upload(factory, cfg, storage, company, job, fx.make_pdf(lines2))
    d2["full_name"] = {"value": "Janet Other"}
    d2["contact"] = {
        "email": {"value": "janet@elsewhere.org"},
        "phone": {"value": "+1 415 555 0134"},
    }
    await run(factory, cfg, storage, FakeLLM(fx.profile_dict()), a.resume_id)
    await run(factory, cfg, storage, FakeLLM(d2), b.resume_id)
    assert await count(factory, Candidate) == 2
    async with factory() as s:
        sug = (await s.execute(sa.select(IdentitySuggestion))).scalar_one()
    assert sug.strength == "weak" and sug.reasons[0] == "phone_match"


async def test_identity_never_crosses_companies(factory, cfg, storage):
    c1, c2 = await make_company(factory, "A"), await make_company(factory, "B")
    j1, j2 = await make_job(factory, c1), await make_job(factory, c2)
    llm = FakeLLM(fx.profile_dict())
    a = await upload(factory, cfg, storage, c1, j1, fx.make_pdf())
    b = await upload(factory, cfg, storage, c2, j2, fx.make_pdf())
    assert (
            b.status == "accepted"
    )  # same hash in another company is NOT a duplicate and has no duplicate flag
    assert (await row(factory, Resume, b.resume_id)).duplicate_of_resume_id is None
    await run(factory, cfg, storage, llm, a.resume_id)
    await run(factory, cfg, storage, llm, b.resume_id)
    assert await count(factory, Candidate) == 2
    assert await count(factory, Candidate, company_id=c1) == 1


async def test_scanned_pdf_end_to_end_with_real_ocr(factory, cfg, storage):
    import shutil

    if not shutil.which(cfg.tesseract_cmd):
        pytest.skip("tesseract missing")
    company = await make_company(factory)
    job = await make_job(factory, company)
    res = await upload(factory, cfg, storage, company, job, fx.make_scanned_pdf())
    d = {"full_name": {"value": "Jane Q. Example"}}
    out = await run(factory, cfg, storage, FakeLLM(d), res.resume_id)
    assert out.kind == "completed"
    async with factory() as s:
        p = (await s.execute(sa.select(ExtractedProfile))).scalar_one()
    assert p.ocr_used and p.extraction_method == "pdf_ocr" and "jane" in p.source_text.lower()


async def test_sweeper_finds_only_stuck_unleased(factory, cfg, storage):
    _, _, res = await setup(factory, cfg, storage)
    assert await service.find_stuck_resume_ids(factory, cfg) == []  # fresh
    async with factory() as s, s.begin():
        (await s.get(Resume, res.resume_id)).status_updated_at = utcnow() - dt.timedelta(hours=2)
    assert await service.find_stuck_resume_ids(factory, cfg) == [res.resume_id]
    async with factory() as s, s.begin():
        (await s.get(Resume, res.resume_id)).lease_expires_at = utcnow() + dt.timedelta(minutes=5)
    assert await service.find_stuck_resume_ids(factory, cfg) == []
