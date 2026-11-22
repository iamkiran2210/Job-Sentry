"""Real-world simulated end-to-end tests for scoring, ranking, verify-once/re-verify,
GitHub profile/projects/languages inspection, AI portfolio checks, and project link HTML checks.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.ai_features.models.application import Application
from app.ai_features.models.candidate import Candidate
from app.ai_features.models.extracted_profile import ExtractedProfile
from app.ai_features.models.resume import Resume
from app.models.job import EmploymentType, Job, WorkMode
from app.models.job_requirement import (
    JobRequirement,
    RequirementCategory,
    RequirementImportance,
    RequirementType,
)
from app.modules.candidate_intelligence.service import CandidateIntelligenceService
from app.modules.candidate_intelligence.verification.external_profiles import (
    verify_github_profile,
    verify_portfolio_ai,
)
from app.modules.candidate_intelligence.verification.project_links import verify_project_links


def _public_resolver(host, port):
    return ["93.184.216.34"]


# ---------------------------------------------------------------------------
# Simulated External Web & GitHub API Fixtures (realistic payloads, offline)
# ---------------------------------------------------------------------------

SIMULATED_GITHUB_USERS: dict[str, dict] = {
    "priyasharma-dev": {
        "login": "priyasharma-dev",
        "html_url": "https://github.com/priyasharma-dev",
        "bio": "Senior Full-Stack & Distributed Systems Engineer | Python, TypeScript, Kubernetes",
        "public_repos": 18,
        "followers": 84,
        "created_at": "2018-04-12T10:00:00Z",
    },
    "marcus-backend": {
        "login": "marcus-backend",
        "html_url": "https://github.com/marcus-backend",
        "bio": "Backend Engineer building Python & Go APIs",
        "public_repos": 8,
        "followers": 19,
        "created_at": "2020-02-01T00:00:00Z",
    },
    "elena-codes": {
        "login": "elena-codes",
        "html_url": "https://github.com/elena-codes",
        "bio": "Full-stack developer (React, TypeScript, Python)",
        "public_repos": 5,
        "followers": 11,
        "created_at": "2023-06-15T00:00:00Z",
    },
    "devon-forks": {
        "login": "devon-forks",
        "html_url": "https://github.com/devon-forks",
        "bio": "Tech enthusiast",
        "public_repos": 2,
        "followers": 1,
        "created_at": "2025-11-01T00:00:00Z",
    },
}

SIMULATED_GITHUB_REPOS: dict[str, list[dict]] = {
    "priyasharma-dev": [
        {
            "name": "event-mesh-fastapi",
            "full_name": "priyasharma-dev/event-mesh-fastapi",
            "html_url": "https://github.com/priyasharma-dev/event-mesh-fastapi",
            "description": "Distributed event streaming platform built with Python, FastAPI, Redis, and Docker.",
            "language": "Python",
            "stargazers_count": 98,
            "forks_count": 14,
            "fork": False,
            "topics": ["python", "fastapi", "redis", "docker", "microservices"],
            "pushed_at": "2026-10-20T12:00:00Z",
        },
        {
            "name": "kube-ops-console",
            "full_name": "priyasharma-dev/kube-ops-console",
            "html_url": "https://github.com/priyasharma-dev/kube-ops-console",
            "description": "React & TypeScript observability dashboard for Kubernetes clusters.",
            "language": "TypeScript",
            "stargazers_count": 47,
            "forks_count": 6,
            "fork": False,
            "topics": ["react", "typescript", "kubernetes", "postgresql"],
            "pushed_at": "2026-10-10T09:00:00Z",
        },
        {
            "name": "awesome-python",
            "full_name": "priyasharma-dev/awesome-python",
            "html_url": "https://github.com/priyasharma-dev/awesome-python",
            "description": "Forked curated list",
            "language": "Python",
            "stargazers_count": 0,
            "forks_count": 0,
            "fork": True,
            "topics": [],
            "pushed_at": "2025-01-05T00:00:00Z",
        },
    ],
    "marcus-backend": [
        {
            "name": "pg-queue-worker",
            "full_name": "marcus-backend/pg-queue-worker",
            "html_url": "https://github.com/marcus-backend/pg-queue-worker",
            "description": "High-throughput PostgreSQL and Redis job queue in Python and FastAPI.",
            "language": "Python",
            "stargazers_count": 22,
            "forks_count": 3,
            "fork": False,
            "topics": ["python", "postgresql", "redis", "docker"],
            "pushed_at": "2026-09-18T12:00:00Z",
        }
    ],
    "elena-codes": [
        {
            "name": "pulse-board",
            "full_name": "elena-codes/pulse-board",
            "html_url": "https://github.com/elena-codes/pulse-board",
            "description": "Team analytics web app using React, TypeScript, FastAPI, and PostgreSQL.",
            "language": "TypeScript",
            "stargazers_count": 9,
            "forks_count": 1,
            "fork": False,
            "topics": ["react", "typescript", "fastapi", "postgresql"],
            "pushed_at": "2026-10-01T10:00:00Z",
        }
    ],
    "devon-forks": [
        {
            "name": "html-css-starter",
            "full_name": "devon-forks/html-css-starter",
            "html_url": "https://github.com/devon-forks/html-css-starter",
            "description": "Forked landing page template",
            "language": "HTML",
            "stargazers_count": 0,
            "forks_count": 0,
            "fork": True,
            "topics": ["html", "css"],
            "pushed_at": "2025-11-02T00:00:00Z",
        },
        {
            "name": "bootstrap-demo",
            "full_name": "devon-forks/bootstrap-demo",
            "html_url": "https://github.com/devon-forks/bootstrap-demo",
            "description": "Forked CSS demo",
            "language": "CSS",
            "stargazers_count": 0,
            "forks_count": 0,
            "fork": True,
            "topics": [],
            "pushed_at": "2025-11-03T00:00:00Z",
        },
    ],
}

SIMULATED_REPO_LANGUAGES: dict[str, dict[str, int]] = {
    "priyasharma-dev/event-mesh-fastapi": {"Python": 84000, "Dockerfile": 4500, "Shell": 2500},
    "priyasharma-dev/kube-ops-console": {"TypeScript": 61000, "CSS": 8000, "Python": 12000},
    "marcus-backend/pg-queue-worker": {"Python": 52000, "Dockerfile": 3000},
    "elena-codes/pulse-board": {"TypeScript": 31000, "Python": 24000},
}

SIMULATED_WEB_PAGES: dict[str, tuple[int, str]] = {
    "https://priyasharma.dev": (
        200,
        """<html><head><title>Priya Sharma — Senior Full-Stack Platform Engineer</title>
        <meta name="description" content="Portfolio of Priya Sharma: Python, FastAPI, React, TypeScript, PostgreSQL, Docker, Kubernetes." /></head>
        <body><h1>Priya Sharma</h1><h2>Featured Projects</h2>
        <h3>Event Mesh FastAPI</h3><p>Distributed microservices event platform built with Python, FastAPI, Redis, PostgreSQL, and Docker.</p>
        <h3>Kube Ops Console</h3><p>React and TypeScript dashboard for Kubernetes observability.</p></body></html>""",
    ),
    "https://github.com/priyasharma-dev/event-mesh-fastapi": (
        200,
        """<html><head><title>priyasharma-dev/event-mesh-fastapi: Distributed event mesh in Python & FastAPI</title></head>
        <body><h1>Event Mesh FastAPI</h1><p>Scalable microservices event router powered by Python, FastAPI, Redis, PostgreSQL, and Docker.</p></body></html>""",
    ),
    "https://marcusvance.io": (
        200,
        """<html><head><title>App</title></head><body><div id="root"></div><script src="/bundle.js"></script></body></html>""",
    ),
    "https://github.com/marcus-backend/pg-queue-worker": (
        200,
        """<html><head><title>marcus-backend/pg-queue-worker: PostgreSQL & Redis Queue</title></head>
        <body><h1>PG Queue Worker</h1><p>Reliable Python FastAPI background worker backed by PostgreSQL, Redis, and Docker.</p></body></html>""",
    ),
    "https://demo.marcusvance.io/gated": (
        200,
        """<html><head><title>Just a moment...</title></head><body>Verify you are human (cf-turnstile)</body></html>""",
    ),
    "https://elenarostova.dev": (
        200,
        """<html><head><title>Elena Rostova | Full-Stack Software Engineer</title></head>
        <body><h1>Elena Rostova</h1><p>Full-Stack Engineer working with React, TypeScript, Python, FastAPI, PostgreSQL, and Docker.</p>
        <h2>Pulse Board</h2><p>Real-time team analytics dashboard.</p></body></html>""",
    ),
    "https://github.com/elena-codes/pulse-board": (
        200,
        """<html><head><title>elena-codes/pulse-board: React + FastAPI Analytics</title></head>
        <body><h1>Pulse Board</h1><p>Built with React, TypeScript, FastAPI, and PostgreSQL.</p></body></html>""",
    ),
    "https://devonbrooks.tech": (
        200,
        """<html><head><title>devonbrooks.tech — This domain is for sale</title></head>
        <body><h1>Buy this domain</h1><p>This domain is parked free, courtesy of Registrar.</p></body></html>""",
    ),
    "https://devonbrooks.tech/k8s-platform": (
        200,
        """<html><head><title>Sunny Valley Bakery & Cakes</title></head>
        <body><h1>Artisan Cupcakes & Sourdough</h1><p>Order fresh pastries, muffins, and wedding cakes daily.</p></body></html>""",
    ),
}


def _github_transport_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.startswith("/users/") and path.endswith("/repos"):
        user = path.split("/")[2]
        if user in SIMULATED_GITHUB_REPOS:
            return httpx.Response(200, json=SIMULATED_GITHUB_REPOS[user])
        return httpx.Response(404, json={"message": "Not Found"})
    if path.startswith("/users/"):
        user = path.split("/")[2]
        if user in SIMULATED_GITHUB_USERS:
            return httpx.Response(200, json=SIMULATED_GITHUB_USERS[user])
        return httpx.Response(404, json={"message": "Not Found"})
    if path.startswith("/repos/") and path.endswith("/languages"):
        parts = path.split("/")
        full_name = f"{parts[2]}/{parts[3]}"
        return httpx.Response(200, json=SIMULATED_REPO_LANGUAGES.get(full_name, {}))
    return httpx.Response(404, json={"message": "Not Found"})


def _web_transport_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url in SIMULATED_WEB_PAGES:
        code, body = SIMULATED_WEB_PAGES[url]
        return httpx.Response(code, text=body, headers={"content-type": "text/html; charset=utf-8"})
    return httpx.Response(404, text="<html><head><title>404 Not Found</title></head><body>Page not found</body></html>")


async def _seed_candidate(
        db_session, company_id, job_id, name: str, email: str, profile_data: dict, source_text: str
):
    cand = Candidate(company_id=company_id, full_name=name, email=email)
    db_session.add(cand)
    await db_session.flush()
    app = Application(company_id=company_id, job_id=job_id, candidate_id=cand.id, status="applied")
    db_session.add(app)
    await db_session.flush()
    resume = Resume(
        company_id=company_id,
        job_id=job_id,
        application_id=app.id,
        original_filename=f"{name.lower().replace(' ', '_')}_resume.pdf",
        extension="pdf",
        content_type="application/pdf",
        size_bytes=4096,
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        storage_backend="local",
        storage_key=f"sim/{app.id}.pdf",
        status="completed",
    )
    db_session.add(resume)
    await db_session.flush()
    db_session.add(
        ExtractedProfile(
            company_id=company_id,
            resume_id=resume.id,
            source_text=source_text,
            profile_data=profile_data,
            extraction_method="pdf_text",
            overall_confidence=0.91,
            ai_engine="pydantic_ai",
            ai_model="heuristic",
            prompt_version="resume_profile-v1",
            schema_version=1,
            ocr_used=False,
            parse_warnings=[],
            extraction_warnings=[],
        )
    )
    await db_session.flush()
    return app


@pytest.mark.asyncio
async def test_github_profile_and_portfolio_ai_verification_units():
    gh_transport = httpx.MockTransport(_github_transport_handler)
    web_transport = httpx.MockTransport(_web_transport_handler)

    # 1. Strong consistent GitHub profile
    priya_profile = {
        "skills": [{"name": "Python"}, {"name": "TypeScript"}, {"name": "Docker"}, {"name": "FastAPI"}],
        "projects": [{"name": "Event Mesh FastAPI", "url": "https://github.com/priyasharma-dev/event-mesh-fastapi"}],
        "employment": [{"title": "Senior Full-Stack Platform Engineer"}],
    }
    gh_priya = await verify_github_profile(
        "https://github.com/priyasharma-dev",
        priya_profile,
        ai_enabled=False,
        transport=gh_transport,
    )
    assert gh_priya.status == "passed"
    assert gh_priya.details["ai_verdict"] == "consistent"
    assert gh_priya.details["original_repos"] == 2
    assert gh_priya.details["forked_repos"] == 1
    assert gh_priya.details["total_stars"] == 145
    assert {l["name"] for l in gh_priya.details["languages"]} >= {"Python", "TypeScript", "Dockerfile"}
    assert "Event Mesh FastAPI" in gh_priya.details["verified_projects"]

    # 2. Fork-only mismatched GitHub profile
    devon_profile = {
        "skills": [{"name": "Python"}, {"name": "Kubernetes"}, {"name": "Docker"}],
        "projects": [{"name": "Kubernetes Platform"}],
        "employment": [{"title": "Staff Platform Engineer"}],
    }
    gh_devon = await verify_github_profile(
        "https://github.com/devon-forks",
        devon_profile,
        ai_enabled=False,
        transport=gh_transport,
    )
    assert gh_devon.status == "needs_review"
    assert gh_devon.details["ai_verdict"] == "inconsistent"
    assert gh_devon.details["original_repos"] == 0
    assert gh_devon.details["discrepancies"]

    # 3. Consistent AI portfolio HTML
    port_priya = await verify_portfolio_ai(
        "https://priyasharma.dev",
        priya_profile,
        ai_enabled=False,
        transport=web_transport,
        resolver=_public_resolver,
    )
    assert port_priya.status == "passed"
    assert port_priya.details["ai_verdict"] == "consistent"
    assert port_priya.details["matched_skills"]
    assert "Event Mesh FastAPI" in port_priya.details["matched_projects"]

    # 4. Parked domain portfolio HTML
    port_devon = await verify_portfolio_ai(
        "https://devonbrooks.tech",
        devon_profile,
        ai_enabled=False,
        transport=web_transport,
        resolver=_public_resolver,
    )
    assert port_devon.status == "failed"
    assert port_devon.details["ai_verdict"] == "parked_or_error"

    # 5. Minimal SPA shell portfolio HTML
    port_marcus = await verify_portfolio_ai(
        "https://marcusvance.io",
        {"skills": [{"name": "Python"}]},
        ai_enabled=False,
        transport=web_transport,
        resolver=_public_resolver,
    )
    assert port_marcus.status == "needs_review"
    assert port_marcus.details["ai_verdict"] == "insufficient_content"


@pytest.mark.asyncio
async def test_real_world_five_candidate_simulation_verify_once_and_reverify_option(
        client: httpx.AsyncClient, db_session, company_with_admin, admin_headers, monkeypatch
):
    gh_transport = httpx.MockTransport(_github_transport_handler)
    web_transport = httpx.MockTransport(_web_transport_handler)

    async def sim_project_links(projects, **kwargs):
        return await verify_project_links(
            projects,
            ai_enabled=False,
            transport=web_transport,
            resolver=_public_resolver,
        )

    async def sim_github(github_url, profile, **kwargs):
        return await verify_github_profile(
            github_url,
            profile,
            ai_enabled=False,
            transport=gh_transport,
        )

    async def sim_portfolio(portfolio_url, profile, **kwargs):
        return await verify_portfolio_ai(
            portfolio_url,
            profile,
            ai_enabled=False,
            transport=web_transport,
            resolver=_public_resolver,
        )

    monkeypatch.setattr(
        "app.modules.candidate_intelligence.service.verify_project_links", sim_project_links
    )
    monkeypatch.setattr(
        "app.modules.candidate_intelligence.service.verify_github_profile", sim_github
    )
    monkeypatch.setattr(
        "app.modules.candidate_intelligence.service.verify_portfolio_ai", sim_portfolio
    )

    company, _ = company_with_admin
    job = Job(
        company_id=company.id,
        title="Senior Full-Stack Platform Engineer",
        description=(
            "Architect distributed microservices and CI/CD pipelines using Python, FastAPI, "
            "TypeScript, React, PostgreSQL, Docker, Kubernetes, and Redis."
        ),
        employment_type=EmploymentType.FULL_TIME,
        work_mode=WorkMode.REMOTE,
    )
    db_session.add(job)
    await db_session.flush()

    db_session.add_all(
        [
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="Python",
                requirement_type=RequirementType.MANDATORY,
                importance=RequirementImportance.HIGH,
                weight=0.0,
                is_mandatory=True,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="TypeScript",
                requirement_type=RequirementType.MANDATORY,
                importance=RequirementImportance.HIGH,
                weight=0.0,
                is_mandatory=True,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="PostgreSQL",
                requirement_type=RequirementType.MANDATORY,
                importance=RequirementImportance.HIGH,
                weight=0.0,
                is_mandatory=True,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="Docker",
                requirement_type=RequirementType.MANDATORY,
                importance=RequirementImportance.HIGH,
                weight=0.0,
                is_mandatory=True,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="FastAPI",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.HIGH,
                weight=0.40,
                is_mandatory=False,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="React",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.HIGH,
                weight=0.30,
                is_mandatory=False,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="Kubernetes",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.MEDIUM,
                weight=0.20,
                is_mandatory=False,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.SKILLS,
                name="Redis",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.LOW,
                weight=0.10,
                is_mandatory=False,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.EXPERIENCE,
                name="4+ years of full-stack or backend engineering",
                requirement_type=RequirementType.MANDATORY,
                importance=RequirementImportance.HIGH,
                weight=0.0,
                is_mandatory=True,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.EDUCATION,
                name="Bachelor's degree in Computer Science",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.MEDIUM,
                weight=0.0,
                is_mandatory=False,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.CERTIFICATION,
                name="AWS Certified Solutions Architect",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.LOW,
                weight=0.0,
                is_mandatory=False,
            ),
            JobRequirement(
                job_id=job.id,
                category=RequirementCategory.RESPONSIBILITY,
                name="Architect distributed microservices and CI/CD pipelines",
                requirement_type=RequirementType.PREFERRED,
                importance=RequirementImportance.MEDIUM,
                weight=0.0,
                is_mandatory=False,
            ),
        ]
    )
    await db_session.flush()

    priya = await _seed_candidate(
        db_session,
        company.id,
        job.id,
        "Priya Sharma",
        "priya.sharma@example.com",
        {
            "contact": {
                "email": {"value": "priya.sharma@example.com"},
                "phone": {"value": "+14155552671"},
                "github_url": {"value": "https://github.com/priyasharma-dev"},
                "portfolio_url": {"value": "https://priyasharma.dev"},
            },
            "skills": [
                {"name": "Python 3"},
                {"name": "TypeScript"},
                {"name": "PostgreSQL"},
                {"name": "FastAPI"},
                {"name": "React.js"},
                {"name": "k8s"},
                {"name": "Redis"},
            ],
            "employment": [
                {
                    "title": "Senior Full-Stack Platform Engineer",
                    "company": "ScaleMesh",
                    "start_date": "2020-01",
                    "is_current": True,
                    "description": "Full-stack and backend engineering architecting distributed microservices and CI/CD pipelines with Python, FastAPI, React, TypeScript, PostgreSQL, Redis, Docker, and Kubernetes.",
                }
            ],
            "projects": [
                {
                    "name": "Event Mesh FastAPI",
                    "description": "Distributed microservices event router with CI/CD pipelines.",
                    "technologies": ["Python", "FastAPI", "Redis", "Docker", "PostgreSQL"],
                    "url": "https://github.com/priyasharma-dev/event-mesh-fastapi",
                }
            ],
            "education": [{"degree": "B.Tech in Computer Science", "field_of_study": "Computer Science"}],
            "certifications": [{"name": "AWS Certified Solutions Architect - Associate"}],
        },
        "Priya Sharma Senior Full-Stack Platform Engineer Python FastAPI React TypeScript Kubernetes Docker.",
    )

    marcus = await _seed_candidate(
        db_session,
        company.id,
        job.id,
        "Marcus Vance",
        "marcus.vance@example.com",
        {
            "contact": {
                "email": {"value": "marcus.vance@example.com"},
                "github_url": {"value": "https://github.com/marcus-backend"},
                "portfolio_url": {"value": "https://marcusvance.io"},
            },
            "skills": [
                {"name": "Python"},
                {"name": "PostgreSQL"},
                {"name": "Docker"},
                {"name": "FastAPI"},
                {"name": "Redis"},
            ],
            "employment": [
                {
                    "title": "Senior Backend Engineer",
                    "company": "DataFlow Systems",
                    "start_date": "2021-01",
                    "is_current": True,
                    "description": "Backend engineering building distributed Python FastAPI microservices with PostgreSQL, Redis, and Docker.",
                }
            ],
            "projects": [
                {
                    "name": "PG Queue Worker",
                    "description": "Distributed microservices background queue in Python.",
                    "technologies": ["Python", "FastAPI", "PostgreSQL", "Redis", "Docker"],
                    "url": "https://github.com/marcus-backend/pg-queue-worker",
                },
                {
                    "name": "Internal Demo Portal",
                    "description": "CI/CD deployment tracker",
                    "technologies": ["Docker"],
                    "url": "https://demo.marcusvance.io/gated",
                },
            ],
            "education": [{"degree": "M.S. in Software Engineering"}],
            "certifications": [],
        },
        "Marcus Vance Senior Backend Engineer Python FastAPI PostgreSQL Redis Docker.",
    )

    elena = await _seed_candidate(
        db_session,
        company.id,
        job.id,
        "Elena Rostova",
        "elena.rostova@example.com",
        {
            "contact": {
                "email": {"value": "elena.rostova@example.com"},
                "github_url": {"value": "https://github.com/elena-codes"},
                "portfolio_url": {"value": "https://elenarostova.dev"},
            },
            "skills": [
                {"name": "Python"},
                {"name": "TypeScript"},
                {"name": "PostgreSQL"},
                {"name": "Docker"},
                {"name": "React"},
                {"name": "FastAPI"},
            ],
            "employment": [
                {
                    "title": "Full-Stack Software Engineer",
                    "company": "BrightLabs",
                    "start_date": "2025-03",
                    "is_current": True,
                    "description": "Full-stack engineering with React, TypeScript, Python, FastAPI, PostgreSQL, and Docker.",
                }
            ],
            "projects": [
                {
                    "name": "Pulse Board",
                    "description": "Real-time team analytics dashboard.",
                    "technologies": ["React", "TypeScript", "FastAPI", "PostgreSQL"],
                    "url": "https://github.com/elena-codes/pulse-board",
                }
            ],
            "education": [{"degree": "B.Sc. in Computer Science"}],
            "certifications": [],
        },
        "Elena Rostova Full-Stack Engineer React TypeScript Python FastAPI PostgreSQL Docker.",
    )

    devon = await _seed_candidate(
        db_session,
        company.id,
        job.id,
        "Devon Brooks",
        "devon.brooks@example.com",
        {
            "contact": {
                "email": {"value": "devon.brooks@example.com"},
                "github_url": {"value": "https://github.com/devon-forks"},
                "portfolio_url": {"value": "https://devonbrooks.tech"},
            },
            "skills": [
                {"name": "Python"},
                {"name": "TypeScript"},
                {"name": "PostgreSQL"},
                {"name": "Docker"},
                {"name": "Kubernetes"},
            ],
            "employment": [
                {
                    "title": "Platform Consultant",
                    "company": "Self-Employed",
                    "start_date": "2020-06",
                    "is_current": True,
                    "description": "Backend engineering and consulting.",
                }
            ],
            "projects": [
                {
                    "name": "Kubernetes Platform",
                    "description": "Enterprise Kubernetes microservices orchestration.",
                    "technologies": ["Kubernetes", "Docker"],
                    "url": "https://devonbrooks.tech/k8s-platform",
                }
            ],
            "education": [{"degree": "Associate Degree in Computing"}],
            "certifications": [],
        },
        "Devon Brooks Platform Consultant Kubernetes Docker.",
    )

    samir = await _seed_candidate(
        db_session,
        company.id,
        job.id,
        "Samir Patel",
        "samir.patel@example.com",
        {
            "contact": {"email": {"value": "samir.patel@example.com"}},
            "skills": [{"name": "Swift"}, {"name": "Kotlin"}, {"name": "Manual QA"}],
            "employment": [
                {
                    "title": "Mobile QA Specialist",
                    "company": "AppCheck",
                    "start_date": "2022-01",
                    "is_current": True,
                    "description": "Manual mobile UI regression testing on iOS and Android devices.",
                }
            ],
            "projects": [
                {
                    "name": "Grocery List App",
                    "description": "Offline shopping checklist app.",
                    "technologies": ["Swift"],
                }
            ],
            "education": [{"degree": "High School Diploma"}],
            "certifications": [],
        },
        "Samir Patel Mobile QA Specialist Swift Kotlin.",
    )

    # Spy on verify() to assert verify-once vs force_verify behavior
    verify_calls: list[uuid.UUID] = []
    orig_verify = CandidateIntelligenceService.verify

    async def spy_verify(db, application_id):
        verify_calls.append(application_id)
        return await orig_verify(db, application_id)

    monkeypatch.setattr(CandidateIntelligenceService, "verify", staticmethod(spy_verify))

    # --- RUN 1: Initial ranking automatically verifies all 5 unverified candidates ONCE ---
    run1 = await client.post(
        f"/api/v1/jobs/{job.id}/rank",
        headers=admin_headers,
        json={"force_rescore": False},
    )
    assert run1.status_code == 200
    data1 = run1.json()["data"]
    assert data1["total_count"] == 5
    assert data1["verified_count"] == 5
    assert set(verify_calls) == {priya.id, marcus.id, elena.id, devon.id, samir.id}

    items = data1["items"]
    assert items[0]["application_id"] == str(priya.id)
    assert items[0]["eligibility"] == "eligible"
    assert items[0]["score"] >= 88.0
    assert items[0]["data_completeness"] == 1.0

    assert items[-1]["application_id"] == str(samir.id)
    assert items[-1]["eligibility"] == "potentially_ineligible"
    assert items[-1]["score"] < 20.0

    # Inspect Priya's persisted analysis & verification details
    priya_analysis = (
        await client.get(f"/api/v1/applications/{priya.id}/analysis", headers=admin_headers)
    ).json()["data"]
    assert priya_analysis["resume"]["overall_confidence"] == pytest.approx(0.91)
    assert priya_analysis["resume"]["extraction_method"] == "pdf_text"
    assert priya_analysis["resume"]["ai_engine"] == "pydantic_ai"
    assert priya_analysis["resume"]["ai_model"] == "heuristic"
    assert priya_analysis["resume"]["prompt_version"] == "resume_profile-v1"
    assert priya_analysis["resume"]["ocr_used"] is False
    assert priya_analysis["resume"]["warnings"] == []
    priya_checks = {c["check_type"]: c for c in priya_analysis["verification_detail"]["checks"]}
    assert priya_checks["github_profile"]["status"] == "passed"
    assert priya_checks["github_profile"]["details"]["ai_verdict"] == "consistent"
    assert priya_checks["portfolio_ai"]["status"] == "passed"
    assert priya_checks["portfolio_ai"]["details"]["ai_verdict"] == "consistent"
    assert priya_checks["project_links"]["status"] == "passed"

    # Inspect Devon's persisted analysis — fake/mismatched external links exposed!
    devon_analysis = (
        await client.get(f"/api/v1/applications/{devon.id}/analysis", headers=admin_headers)
    ).json()["data"]
    devon_checks = {c["check_type"]: c for c in devon_analysis["verification_detail"]["checks"]}
    assert devon_checks["portfolio_ai"]["status"] == "failed"
    assert devon_checks["portfolio_ai"]["details"]["ai_verdict"] == "parked_or_error"
    assert devon_checks["github_profile"]["status"] == "needs_review"
    assert devon_checks["github_profile"]["details"]["ai_verdict"] == "inconsistent"
    assert devon_checks["project_links"]["status"] == "needs_review"
    assert devon_checks["project_links"]["details"]["projects"][0]["ai_verdict"] == "inconsistent"

    # Inspect Marcus's verification — SPA portfolio + bot-gated demo link flagged needs_review
    marcus_analysis = (
        await client.get(f"/api/v1/applications/{marcus.id}/analysis", headers=admin_headers)
    ).json()["data"]
    marcus_checks = {c["check_type"]: c for c in marcus_analysis["verification_detail"]["checks"]}
    assert marcus_checks["github_profile"]["status"] == "passed"
    assert marcus_checks["portfolio_ai"]["status"] == "needs_review"
    assert marcus_checks["portfolio_ai"]["details"]["ai_verdict"] == "insufficient_content"
    assert marcus_checks["project_links"]["status"] == "needs_review"

    # --- RUN 2: Re-ranking WITHOUT force_verify skips verification completely (verify once!) ---
    verify_calls.clear()
    run2 = await client.post(
        f"/api/v1/jobs/{job.id}/rank",
        headers=admin_headers,
        json={"force_rescore": True, "force_verify": False},
    )
    assert run2.status_code == 200
    assert run2.json()["data"]["verified_count"] == 0
    assert verify_calls == []

    # --- RUN 3: Re-ranking a specific individual WITH force_verify=True re-verifies ONLY that individual ---
    verify_calls.clear()
    run3 = await client.post(
        f"/api/v1/jobs/{job.id}/rank",
        headers=admin_headers,
        json={"application_ids": [str(priya.id)], "force_rescore": True, "force_verify": True},
    )
    assert run3.status_code == 200
    assert run3.json()["data"]["verified_count"] == 1
    assert run3.json()["data"]["total_count"] == 5
    assert verify_calls == [priya.id]

    # --- RUN 4: Force re-score all WITH force_verify=True re-verifies all 5 candidates ---
    verify_calls.clear()
    run4 = await client.post(
        f"/api/v1/jobs/{job.id}/rank",
        headers=admin_headers,
        json={"force_rescore": True, "force_verify": True},
    )
    assert run4.status_code == 200
    assert run4.json()["data"]["verified_count"] == 5
    assert set(verify_calls) == {priya.id, marcus.id, elena.id, devon.id, samir.id}
