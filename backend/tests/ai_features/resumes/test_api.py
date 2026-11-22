"""HTTP-level tests incl. Phase 2 job sharing. Access rules come from the `policy` fixture (documented
JobsService.get_job semantics); test_access_seam.py checks the real JobsService wiring in the sandbox."""

import uuid
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from sqlalchemy import select

from app.core.database import get_db
from app.core.dependencies import get_current_active_user
from app.ai_features.candidates import router as candidates_router
from app.ai_features.resumes import router as resumes_router
from app.ai_features.resumes.config import get_settings
from app.ai_features.resumes.dispatch import get_dispatcher
from app.ai_features.resumes.errors import FailureCode, PipelineError
from app.ai_features.resumes.storage import get_storage
from app.ai_features.models.application import Application
from app.ai_features.models.resume import Resume
from app.modules.application_status.models import ApplicationStatusHistory

from . import fixtures as fx
from .helpers import (
    FakeLLM,
    RecordingDispatcher,
    count,
    make_company,
    make_job,
    make_user,
    run,
)

pytestmark = pytest.mark.asyncio
API = "/api/v1"


@pytest_asyncio.fixture
async def env(factory, cfg, storage, policy):
    app = FastAPI()
    app.include_router(resumes_router, prefix=API)
    app.include_router(candidates_router, prefix=API)
    disp, users = RecordingDispatcher(), {}

    async def db_dep():
        async with factory() as s:
            yield s

    async def user_dep(request: Request):
        return users[uuid.UUID(request.headers["x-user"])]

    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[get_current_active_user] = user_dep
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_dispatcher] = lambda: disp
    app.dependency_overrides[get_settings] = lambda: cfg

    e = SimpleNamespace(disp=disp, factory=factory, cfg=cfg, storage=storage, policy=policy)
    e.a, e.b = await make_company(factory, "A"), await make_company(factory, "B")
    e.job_a, e.job_a2, e.job_b = (
        await make_job(factory, e.a),
        await make_job(factory, e.a),
        await make_job(factory, e.b),
    )
    e.member_a, e.member_b = (
        await make_user(factory, e.a),
        await make_user(factory, e.b),
    )
    e.viewer, e.editor, e.outsider = (
        await make_user(factory),
        await make_user(factory),
        await make_user(factory),
    )
    for u in (e.member_a, e.member_b, e.viewer, e.editor, e.outsider):
        users[u.id] = u
    policy.grants[(e.viewer.id, e.job_a)] = "viewer"
    policy.grants[(e.editor.id, e.job_a)] = "editor"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        e.client = c
        e.h = lambda u: {"x-user": str(u.id)}
        yield e


def files(*items):
    return [("files", (n, d, "application/octet-stream")) for n, d in items]


async def up(env, user, job, *items):
    return await env.client.post(
        f"{API}/jobs/{job}/resumes", headers=env.h(user), files=files(*items)
    )


def results(r):
    return r.json()["data"]["results"]


# ------------------------------------------------------------------ upload behaviour
async def test_multi_file_upload_returns_promptly_with_status(env):
    r = await up(
        env,
        env.member_a,
        env.job_a,
        ("a.pdf", fx.make_pdf()),
        ("b.docx", fx.make_docx()),
        ("evil.exe", b"MZ" + b"\0" * 64),
    )
    assert r.status_code == 202 and r.json()["success"] is True
    res = results(r)
    assert [x["status"] for x in res] == ["accepted", "accepted", "rejected"]
    assert (
            res[2]["reason_code"] == "UNSUPPORTED_EXTENSION" and res[0]["processing_status"] == "queued"
    )
    assert len(env.disp.ids) == 2  # handed to the worker; nothing parsed during the request
    assert await count(env.factory, Resume) == 2 and await count(env.factory, Application) == 2
    body = (
        await env.client.get(f"{API}/resumes/{res[0]['resume_id']}", headers=env.h(env.member_a))
    ).json()["data"]
    assert body["status"] == "queued" and body["profile"] is None
    assert "storage_key" not in body and "source_text" not in str(body)


async def test_all_rejected_is_422(env):
    r = await up(env, env.member_a, env.job_a, ("x.txt", b"hello"))
    assert r.status_code == 422 and results(r)[0]["status"] == "rejected"


async def test_duplicate_upload_is_idempotent(env):
    data = fx.make_pdf()
    first = results(await up(env, env.member_a, env.job_a, ("a.pdf", data)))[0]
    again = results(await up(env, env.member_a, env.job_a, ("renamed.pdf", data)))[0]
    assert again["status"] == "duplicate" and again["resume_id"] == first["resume_id"]
    assert (
            await count(env.factory, Resume) == 1
            and await count(env.factory, Application) == 1
            and len(env.disp.ids) == 1
    )


async def test_too_many_files_and_oversize(env):
    env.cfg.max_files_per_request = 2
    r = await up(env, env.member_a, env.job_a, *[(f"{i}.pdf", fx.make_pdf()) for i in range(3)])
    assert r.status_code == 413
    env.cfg.max_files_per_request, env.cfg.max_upload_bytes = 20, 500
    r = await up(env, env.member_a, env.job_a, ("big.pdf", fx.make_pdf() + b"0" * 2000))
    assert (
            r.status_code == 422
            and results(r)[0]["reason_code"] == "FILE_TOO_LARGE"
            and await count(env.factory, Resume) == 0
    )


async def test_enqueue_outage_leaves_uploaded_then_retry_requeues(env):
    env.disp.fail = True
    r = await up(env, env.member_a, env.job_a, ("a.pdf", fx.make_pdf()))
    item = results(r)[0]
    assert r.status_code == 202 and item["processing_status"] == "uploaded"
    st = (
        await env.client.get(
            f"{API}/resumes/{item['resume_id']}/status", headers=env.h(env.member_a)
        )
    ).json()["data"]
    assert st["status"] == "uploaded" and st["retryable"] is True
    env.disp.fail = False
    rr = await env.client.post(
        f"{API}/resumes/{item['resume_id']}/retry", headers=env.h(env.member_a)
    )
    assert (
            rr.status_code == 202
            and rr.json()["data"]["status"] == "queued"
            and env.disp.ids == [uuid.UUID(item["resume_id"])]
    )


async def test_full_flow_results_visible_through_api(env):
    item = results(await up(env, env.member_a, env.job_a, ("a.pdf", fx.make_pdf())))[0]
    rid = item["resume_id"]
    await run(env.factory, env.cfg, env.storage, FakeLLM(fx.profile_dict()), uuid.UUID(rid))
    h = env.h(env.member_a)
    st = (await env.client.get(f"{API}/resumes/{rid}/status", headers=h)).json()["data"]
    assert st["status"] == "completed" and st["retryable"] is False
    p = (await env.client.get(f"{API}/resumes/{rid}", headers=h)).json()["data"]["profile"]
    assert p["data_origin"] == "resume_claims_unverified" and p["extraction_method"] == "pdf_text"
    assert (
            p["data"]["contact"]["email"]["value"] == "jane.example@example.com"
            and p["ai_engine"] == "fake"
    )
    app = (await env.client.get(f"{API}/applications/{item['application_id']}", headers=h)).json()[
        "data"
    ]
    assert app["status"] == "analyzed" and app["candidate_id"] and app["resumes"][0]["profile"]
    async with env.factory() as session:
        status_history = (
            (
                await session.execute(
                    select(ApplicationStatusHistory)
                    .where(
                        ApplicationStatusHistory.application_id == uuid.UUID(item["application_id"])
                    )
                    .order_by(ApplicationStatusHistory.created_at)
                )
            )
            .scalars()
            .all()
        )
    assert [(row.from_status, row.to_status, row.actor_type) for row in status_history] == [
        ("applied", "processing", "system"),
        ("processing", "analyzed", "system"),
    ]
    cand = (await env.client.get(f"{API}/candidates/{app['candidate_id']}", headers=h)).json()[
        "data"
    ]
    assert (
            cand["full_name"] == "Jane Q. Example"
            and cand["latest_profile"]
            and len(cand["applications"]) == 1
    )


async def test_failed_resume_reports_safe_reason_and_retry_rules(env):
    rid = results(await up(env, env.member_a, env.job_a, ("a.pdf", fx.make_pdf())))[0]["resume_id"]
    h = env.h(env.member_a)
    assert (
               await env.client.post(f"{API}/resumes/{rid}/retry", headers=h)
           ).status_code == 409  # queued: not retryable
    await run(
        env.factory,
        env.cfg,
        env.storage,
        FakeLLM(PipelineError(FailureCode.LLM_NOT_CONFIGURED)),
        uuid.UUID(rid),
    )
    st = (await env.client.get(f"{API}/resumes/{rid}/status", headers=h)).json()["data"]
    assert (
            st["status"] == "failed" and st["failure_code"] == "LLM_NOT_CONFIGURED" and st["retryable"]
    )
    assert st["failure_message"] == "The analysis service is not configured."
    async with env.factory() as session:
        resume_row = await session.get(Resume, uuid.UUID(rid))
        app_row = await session.get(Application, resume_row.application_id)
        assert app_row.status == "applied"
    r = await env.client.post(f"{API}/resumes/{rid}/retry", headers=h)
    assert (
            r.status_code == 202
            and r.json()["data"]["status"] == "queued"
            and r.json()["data"]["failure_code"] is None
    )


# ------------------------------------------------------------------ tenant isolation + Phase 2 sharing
async def test_other_company_and_outsiders_are_blocked_everywhere(env):
    item = results(await up(env, env.member_a, env.job_a, ("a.pdf", fx.make_pdf())))[0]
    rid, aid = item["resume_id"], item["application_id"]
    await run(env.factory, env.cfg, env.storage, FakeLLM(fx.profile_dict()), uuid.UUID(rid))
    cid = (await env.client.get(f"{API}/applications/{aid}", headers=env.h(env.member_a))).json()[
        "data"
    ]["candidate_id"]
    urls = [
        f"/resumes/{rid}",
        f"/resumes/{rid}/status",
        f"/applications/{aid}",
        f"/candidates/{cid}",
        f"/jobs/{env.job_a}/applicants",
    ]
    for who in (
            env.member_b,
            env.outsider,
    ):  # other company's member; registered user with no grant
        for u in urls:
            r = await env.client.get(API + u, headers=env.h(who))
            assert r.status_code == 404 and rid not in r.text and "jane" not in r.text.lower(), (
                who,
                u,
            )
        assert (
                   await env.client.post(f"{API}/resumes/{rid}/retry", headers=env.h(who))
               ).status_code == 404
        assert (
                   await up(
                       env,
                       who,
                       env.job_a,
                       ("n.pdf", fx.make_pdf(["other file with enough text to parse ok"])),
                   )
               ).status_code == 404
    assert (
               await env.client.get(f"{API}/resumes/{uuid.uuid4()}", headers=env.h(env.member_a))
           ).status_code == 404
    assert await count(env.factory, Resume) == 1


async def test_viewer_grant_can_read_but_not_upload_or_retry(env):
    item = results(await up(env, env.member_a, env.job_a, ("a.pdf", fx.make_pdf())))[0]
    rid, aid = item["resume_id"], item["application_id"]
    await run(
        env.factory,
        env.cfg,
        env.storage,
        FakeLLM(PipelineError(FailureCode.LLM_NOT_CONFIGURED)),
        uuid.UUID(rid),
    )
    v = env.h(env.viewer)
    for u in (f"/resumes/{rid}", f"/resumes/{rid}/status", f"/applications/{aid}"):
        assert (await env.client.get(API + u, headers=v)).status_code == 200, u
    assert (await env.client.post(f"{API}/resumes/{rid}/retry", headers=v)).status_code == 403
    r = await up(
        env,
        env.viewer,
        env.job_a,
        ("n.pdf", fx.make_pdf(["another resume with enough text to be parsed"])),
    )
    assert r.status_code == 403 and await count(env.factory, Resume) == 1
    assert (await env.client.get(f"{API}/resumes/{rid}/status", headers=v)).json()["data"][
               "status"
           ] == "failed"  # retry did nothing


async def test_editor_grant_can_upload_and_retry(env):
    r = await up(env, env.editor, env.job_a, ("a.pdf", fx.make_pdf()))
    assert r.status_code == 202
    rid = results(r)[0]["resume_id"]
    await run(
        env.factory,
        env.cfg,
        env.storage,
        FakeLLM(PipelineError(FailureCode.LLM_NOT_CONFIGURED)),
        uuid.UUID(rid),
    )
    rr = await env.client.post(f"{API}/resumes/{rid}/retry", headers=env.h(env.editor))
    assert rr.status_code == 202
    assert (
               await up(env, env.editor, env.job_a2, ("b.pdf", fx.make_pdf()))
           ).status_code == 404  # grant is for ONE job only
    row_ = await env.client.get(f"{API}/resumes/{rid}", headers=env.h(env.editor))
    assert row_.status_code == 200


async def test_job_grant_user_sees_candidate_only_through_granted_jobs(env):
    """One candidate, two jobs in the same company. A viewer on job A must not learn about job A2's application
    or profile, nor about identity-review hints; a company member sees everything."""
    same = fx.make_pdf()
    r1 = results(await up(env, env.member_a, env.job_a, ("a.pdf", same)))[0]
    r2 = results(await up(env, env.member_a, env.job_a2, ("a.pdf", same)))[0]
    llm = FakeLLM(fx.profile_dict())
    for r in (r1, r2):
        await run(env.factory, env.cfg, env.storage, llm, uuid.UUID(r["resume_id"]))
    cid = (
        await env.client.get(
            f"{API}/applications/{r1['application_id']}", headers=env.h(env.member_a)
        )
    ).json()["data"]["candidate_id"]
    member = (await env.client.get(f"{API}/candidates/{cid}", headers=env.h(env.member_a))).json()[
        "data"
    ]
    assert {a["job_id"] for a in member["applications"]} == {
        str(env.job_a),
        str(env.job_a2),
    }
    viewer = (await env.client.get(f"{API}/candidates/{cid}", headers=env.h(env.viewer))).json()[
        "data"
    ]
    assert [a["job_id"] for a in viewer["applications"]] == [str(env.job_a)]
    assert viewer["latest_profile"]["resume_id"] == r1["resume_id"]
    assert viewer["identity_review"] == []
    app2 = await env.client.get(
        f"{API}/applications/{r2['application_id']}", headers=env.h(env.viewer)
    )
    assert app2.status_code == 404  # same candidate, but a job the viewer has no grant for


async def test_identity_review_hints_visible_to_members_only(env):
    llm_a = FakeLLM(fx.profile_dict())
    d2 = fx.profile_dict()
    d2["full_name"], d2["contact"] = (
        {"value": "Janet Other"},
        {
            "email": {"value": "janet@elsewhere.org"},
            "phone": {"value": "+1 415 555 0134"},
        },
    )
    lines2 = [
        "Janet Other",
        "janet@elsewhere.org | +1 415 555 0134",
        "Python developer with enough text to parse",
    ]
    a = results(await up(env, env.member_a, env.job_a, ("a.pdf", fx.make_pdf())))[0]
    b = results(await up(env, env.member_a, env.job_a, ("b.pdf", fx.make_pdf(lines2))))[0]
    await run(env.factory, env.cfg, env.storage, llm_a, uuid.UUID(a["resume_id"]))
    await run(env.factory, env.cfg, env.storage, FakeLLM(d2), uuid.UUID(b["resume_id"]))
    cid = (
        await env.client.get(
            f"{API}/applications/{b['application_id']}", headers=env.h(env.member_a)
        )
    ).json()["data"]["candidate_id"]
    member = (await env.client.get(f"{API}/candidates/{cid}", headers=env.h(env.member_a))).json()[
        "data"
    ]
    assert member["identity_review"] and member["identity_review"][0]["strength"] == "weak"
    viewer = (await env.client.get(f"{API}/candidates/{cid}", headers=env.h(env.viewer))).json()[
        "data"
    ]
    assert viewer["identity_review"] == []


async def test_job_applicants_endpoint_rbac_and_data(env):
    """RBAC check for GET /jobs/{job_id}/applicants:
    Company member, job viewer, and job editor can see applicants.
    Other companies and outsiders receive 404.
    """
    item = results(await up(env, env.member_a, env.job_a, ("a.pdf", fx.make_pdf())))[0]
    rid = item["resume_id"]
    await run(env.factory, env.cfg, env.storage, FakeLLM(fx.profile_dict()), uuid.UUID(rid))

    # 1. Company member has access
    res = await env.client.get(f"{API}/jobs/{env.job_a}/applicants", headers=env.h(env.member_a))
    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data) == 1
    applicant = data[0]
    assert applicant["job_id"] == str(env.job_a)
    assert applicant["status"] == "analyzed"
    assert "jane" in applicant["full_name"].lower()
    assert applicant["email"] == "jane.example@example.com"
    assert applicant["resume_id"] == rid
    assert applicant["resume_status"] == "completed"
    assert applicant["candidate"] is not None
    assert applicant["latest_profile"] is not None

    # 2. Viewer grant on job_a has read access
    res_v = await env.client.get(f"{API}/jobs/{env.job_a}/applicants", headers=env.h(env.viewer))
    assert res_v.status_code == 200
    assert len(res_v.json()["data"]) == 1

    # 3. Editor grant on job_a has access
    res_e = await env.client.get(f"{API}/jobs/{env.job_a}/applicants", headers=env.h(env.editor))
    assert res_e.status_code == 200
    assert len(res_e.json()["data"]) == 1

    # 4. Other company member is blocked (404)
    res_b = await env.client.get(f"{API}/jobs/{env.job_a}/applicants", headers=env.h(env.member_b))
    assert res_b.status_code == 404

    # 5. Outsider with no grant is blocked (404)
    res_out = await env.client.get(
        f"{API}/jobs/{env.job_a}/applicants", headers=env.h(env.outsider)
    )
    assert res_out.status_code == 404

    # 6. Status filter
    res_filter_match = await env.client.get(
        f"{API}/jobs/{env.job_a}/applicants?status=analyzed", headers=env.h(env.member_a)
    )
    assert len(res_filter_match.json()["data"]) == 1

    res_filter_none = await env.client.get(
        f"{API}/jobs/{env.job_a}/applicants?status=rejected", headers=env.h(env.member_a)
    )
    assert len(res_filter_none.json()["data"]) == 0

    # 7. Invalid status rejected by Literal schema (422)
    res_filter_invalid = await env.client.get(
        f"{API}/jobs/{env.job_a}/applicants?status=invalid_status", headers=env.h(env.member_a)
    )
    assert res_filter_invalid.status_code == 422

    # 8. Alias /jobs/{job_id}/applications
    res_alias = await env.client.get(
        f"{API}/jobs/{env.job_a}/applications", headers=env.h(env.member_a)
    )
    assert res_alias.status_code == 200
    assert len(res_alias.json()["data"]) == 1
