from __future__ import annotations

import uuid

import httpx
import pytest

from app.ai_features.models.application import Application
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.resume import Resume
from app.models.job import EmploymentType, Job, WorkMode
from app.modules.candidate_intelligence.verification.project_links import (
    ProjectLinkAIVerdict,
    extract_html_summary,
    verify_project_links,
)


def _public_resolver(host, port):
    return ["93.184.216.34"]


def test_extract_html_summary_strips_scripts_and_extracts_metadata():
    html = """
    <html>
      <head>
        <title>Distributed Task Queue - FastAPI & Redis</title>
        <meta name="description" content="High-throughput Python task queue built with FastAPI and Redis." />
        <style>body { color: red; }</style>
        <script>console.log("ignore secret script");</script>
      </head>
      <body>
        <h1>Distributed Task Queue</h1>
        <h2>Architecture</h2>
        <p>Built with Python, FastAPI, Redis, and Docker containers.</p>
      </body>
    </html>
    """
    summary = extract_html_summary(html)
    assert summary.title == "Distributed Task Queue - FastAPI & Redis"
    assert "FastAPI and Redis" in summary.meta_description
    assert summary.headings == ("Distributed Task Queue", "Architecture")
    assert "ignore secret script" not in summary.visible_text
    assert "Docker containers" in summary.visible_text
    assert summary.bot_gated is False
    assert summary.parked_or_error is False


@pytest.mark.asyncio
async def test_project_links_consistent_html_passes_with_ai_and_html_details():
    html = """
    <html>
      <head>
        <title>alice/task-queue: Distributed Task Queue in Python</title>
        <meta name="description" content="Scalable FastAPI and Redis distributed task queue." />
      </head>
      <body>
        <h1>Distributed Task Queue</h1>
        <p>Implemented worker pools using Python, FastAPI, Redis, and Docker.</p>
      </body>
    </html>
    """
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=html, headers={"content-type": "text/html"})
    )
    result = await verify_project_links(
        [
            {
                "name": "Distributed Task Queue",
                "description": "Built a scalable worker queue using FastAPI and Redis.",
                "technologies": ["Python", "FastAPI", "Redis", "Docker"],
                "url": "https://github.com/alice/task-queue",
            }
        ],
        ai_enabled=False,
        transport=transport,
        resolver=_public_resolver,
    )
    assert result.check_type == "project_links"
    assert result.status == "passed"
    assert result.details["total_links"] == 1
    assert result.details["consistent_links"] == 1
    proj = result.details["projects"][0]
    assert proj["http_status"] == 200
    assert proj["ai_verdict"] == "consistent"
    assert proj["ai_relevance_score"] >= 0.6
    assert "task-queue" in proj["html_title"]
    assert proj["matched_claims"]


@pytest.mark.asyncio
async def test_project_links_unrelated_html_is_flagged_needs_review():
    html = """
    <html>
      <head><title>Grandma's Bakery & Pastry Recipes</title></head>
      <body>
        <h1>Fresh Sourdough Bread</h1>
        <p>Bake artisan croissants, cinnamon rolls, and chocolate cake every morning.</p>
      </body>
    </html>
    """
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=html, headers={"content-type": "text/html"})
    )
    result = await verify_project_links(
        [
            {
                "name": "Kubernetes Ingress Controller",
                "description": "High-performance Go load balancer for Kubernetes clusters.",
                "technologies": ["Go", "Kubernetes", "gRPC"],
                "url": "https://example.com/k8s-controller",
            }
        ],
        ai_enabled=False,
        transport=transport,
        resolver=_public_resolver,
    )
    assert result.status == "needs_review"
    proj = result.details["projects"][0]
    assert proj["ai_verdict"] == "inconsistent"
    assert proj["discrepancies"]


@pytest.mark.asyncio
async def test_project_links_soft_404_and_ssrf_fail_and_bot_gate_needs_review():
    parked_html = "<html><head><title>404 Page Not Found</title></head><body><h1>Repository not found</h1></body></html>"
    parked = await verify_project_links(
        [{"name": "Ghost App", "url": "https://example.com/ghost"}],
        ai_enabled=False,
        transport=httpx.MockTransport(lambda req: httpx.Response(200, text=parked_html)),
        resolver=_public_resolver,
    )
    assert parked.status == "failed"
    assert parked.details["projects"][0]["ai_verdict"] == "parked_or_error"

    ssrf = await verify_project_links(
        [{"name": "Internal Admin", "url": "http://169.254.169.254/latest/meta-data/"}],
        ai_enabled=False,
        transport=httpx.MockTransport(lambda req: httpx.Response(200, text="secret")),
        resolver=_public_resolver,
    )
    assert ssrf.status == "failed"
    assert ssrf.details["projects"][0]["reason_code"] == "ssrf_blocked"

    bot_html = "<html><head><title>Just a moment...</title></head><body>Verify you are human (cf-turnstile)</body></html>"
    gated = await verify_project_links(
        [{"name": "Protected Demo", "url": "https://example.com/protected"}],
        ai_enabled=False,
        transport=httpx.MockTransport(lambda req: httpx.Response(200, text=bot_html)),
        resolver=_public_resolver,
    )
    assert gated.status == "needs_review"
    assert gated.details["projects"][0]["reason_code"] == "bot_or_access_gated"


@pytest.mark.asyncio
async def test_project_links_supports_custom_ai_analyzer_and_verify_endpoint(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers, monkeypatch
):
    async def fake_ai(project, html, final_url):
        assert "Telemetry Dashboard" in html.title
        return ProjectLinkAIVerdict(
            verdict="consistent",
            relevance_score=0.92,
            matched_claims=["Telemetry Dashboard", "SvelteKit"],
            discrepancies=[],
            summary="AI confirmed page HTML describes the claimed SvelteKit Telemetry Dashboard.",
        )

    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            text="<html><head><title>Telemetry Dashboard</title></head><body><h1>Telemetry Dashboard</h1><p>Built with SvelteKit.</p></body></html>",
        )
    )
    direct = await verify_project_links(
        [{"name": "Telemetry Dashboard", "technologies": ["SvelteKit"], "url": "https://example.com/dash"}],
        transport=transport,
        resolver=_public_resolver,
        ai_analyzer=fake_ai,
    )
    assert direct.status == "passed"
    assert direct.details["projects"][0]["ai_relevance_score"] == 0.92
    assert direct.details["projects"][0]["analysis_mode"] == "custom_ai"

    # End-to-end POST /applications/{id}/verify returns project_links check
    company, _ = company_with_admin
    job = Job(
        company_id=company.id,
        title="Fullstack Engineer",
        description="Build web apps",
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
    )
    db_session.add(job)
    await db_session.flush()
    app = Application(company_id=company.id, job_id=job.id, status="applied")
    db_session.add(app)
    await db_session.flush()
    resume = Resume(
        company_id=company.id,
        job_id=job.id,
        application_id=app.id,
        original_filename="candidate.pdf",
        extension="pdf",
        content_type="application/pdf",
        size_bytes=128,
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        storage_backend="local",
        storage_key=f"test/{app.id}.pdf",
    )
    db_session.add(resume)
    await db_session.flush()
    db_session.add(
        ExtractedProfile(
            company_id=company.id,
            resume_id=resume.id,
            source_text="Built Telemetry Dashboard at https://example.com/dash",
            profile_data={
                "skills": [{"name": "SvelteKit"}],
                "employment": [],
                "education": [],
                "projects": [
                    {
                        "name": "Telemetry Dashboard",
                        "description": "Real-time metrics dashboard",
                        "technologies": ["SvelteKit"],
                        "url": "https://example.com/dash",
                    }
                ],
                "certifications": [],
                "contact": {},
            },
        )
    )
    await db_session.flush()

    async def stub_verify_projects(projects, **kwargs):
        return await verify_project_links(
            projects,
            transport=transport,
            resolver=_public_resolver,
            ai_analyzer=fake_ai,
        )

    monkeypatch.setattr(
        "app.modules.candidate_intelligence.service.verify_project_links", stub_verify_projects
    )

    resp = await client.post(f"/api/v1/applications/{app.id}/verify", headers=admin_headers)
    assert resp.status_code == 200
    checks = resp.json()["data"]["checks"]
    project_check = next(c for c in checks if c["check_type"] == "project_links")
    assert project_check["status"] == "passed"
    assert project_check["details"]["projects"][0]["ai_verdict"] == "consistent"
    assert project_check["details"]["projects"][0]["html_title"] == "Telemetry Dashboard"
