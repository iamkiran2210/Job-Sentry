# Job Sentry — AI Recruitment Intelligence & Fraud Risk Platform

**Job Sentry** is an end-to-end, multi-agent recruitment intelligence and fraud-risk analysis platform built with *
*FastAPI**, **Celery + Redis**, **PostgreSQL (`pgvector`)**, **Pydantic AI + DSPy**, and a **SvelteKit 5 + Tailwind v4**
web application.

It automates unstructured resume parsing, deep external profile verification (LinkedIn via Bright Data SDK, GitHub,
portfolios, project links, email DNS/MX, content authenticity), deterministic explainable scoring, and multi-agent
hiring recommendations — while preserving strict auditability, PII hygiene, and human-in-the-loop control (with optional
auto-threshold actions).

---

## Table of Contents

1. [Key Features](#1-key-features)
2. [System Architecture](#2-system-architecture)
3. [AI Agent & Optimization Pipeline](#3-ai-agent--optimization-pipeline)
4. [Tech Stack](#4-tech-stack)
5. [Project Structure](#5-project-structure)
6. [Quick Start with Docker Compose (Recommended)](#6-quick-start-with-docker-compose-recommended)
7. [Configuration & Environment Variables](#7-configuration--environment-variables)
8. [API Overview](#8-api-overview)
9. [Running Locally Without Docker](#9-running-locally-without-docker)
10. [Testing & Verification](#10-testing--verification)
11. [Cloudflare Tunnel & Production Deployment](#11-cloudflare-tunnel--production-deployment)

---

## 1. Key Features

### Resume Ingestion & Grounded Extraction

- **Multi-Format Parsing:** Supports PDF (2-column layout preservation + clickable embedded hyperlink extraction via
  PyMuPDF), DOCX (paragraphs, tables, and hyperlinks via `python-docx`), and scanned images/PDFs (Pillow sharpening +
  Tesseract OCR with 2-column reading-order recovery).
- **Magic-Byte & Size Validation:** Strict file-type signature checks, SHA-256 deduplication, and configurable upload
  limits.
- **Verbatim-Grounded AI Extraction:** Structured extraction of identity, contact links, skills, employment history,
  dates, education, projects, certifications, and explicit experience claims — every claim backed by verbatim source
  quotes and confidence scores.
- **Async Background Processing:** Celery workers + Redis broker process resumes asynchronously with Celery Beat
  recovery for stuck tasks.

### Verification & Fraud Risk Engine (12 Automated Checks)

Every candidate is automatically verified on first ranking (and can be re-verified on demand), producing a **0–100
Composite Fraud Risk Score** (`low` / `medium` / `high` + flags):

1. **Email Syntax Check** — RFC validation, role-account detection, and whitespace normalization.
2. **Email Domain DNS/MX Check** — Live DNS `MX`/`A` record lookup (`dnspython`) + disposable throwaway domain
   blocking (`mailinator`, `tempmail`, `yopmail`, `10minutemail`, etc.) and `NXDOMAIN` detection.
3. **Phone Format Check** — International E.164 validation via `phonenumbers` with PII masking in verification logs.
4. **Resume Completeness Check** — Evaluates section coverage (skills, employment, education, projects, certifications).
5. **Timeline Consistency Check** — Flags overlapping roles, unexplained multi-month gaps, inverted dates, and future
   dates.
6. **Duplicate Signal Check** — Cross-checks duplicate email, phone, or SHA-256 resume hash across jobs/company.
7. **Content Authenticity & Anti-Fraud Check** — Detects prompt-injection attempts (e.g.
   `"ignore previous instructions"`), unfilled AI/template placeholders (`[Company Name]`, `"As an AI language model"`),
   boilerplate stuffing, and duplicated lines.
8. **GitHub URL & Deep GitHub Profile Check** — Inspects public GitHub repositories, original vs. forked ratio,
   concurrent repo language byte shares, and AI/heuristic alignment with resume claims.
9. **Portfolio URL & Portfolio AI Audit** — SSRF-hardened safe HTML fetching + AI consistency verification (flags
   parked/for-sale domains, 404s, SPA shells, and unrelated templates).
10. **Project Links HTML + AI Audit** — Fetches and cross-checks live project/repo links listed on the resume.
11. **LinkedIn Profile Verification (Official Bright Data SDK)** — Uses `brightdata-sdk` (`BrightDataClient`) to fetch
    public LinkedIn profiles (including nested company `positions`, education years, certifications, projects, skills,
    connections/followers) and cross-checks **name/identity match**, **timeline alignment**, employers, roles,
    education, certifications, projects, and skills.
12. **SSRF & Security Protections** — Blocks loopback/private/link-local/metadata IPs, enforces redirect hop limits, and
    strips cookies/auth headers on external fetches.

### Explainable Scoring & 4-Agent Decision Panel

- **Weighted Deterministic Scoring:** Category-weighted scoring across Skills, Experience, Projects, Education, and
  Certifications with mandatory requirement pass/fail gates, confidence bounds (`lower_bound`–`upper_bound`), and
  grounded `ScoreEvidenceRecord` items.
- **Plain-English AI Score Summary:** Short, jargon-free overview plus Strengths & Gaps bullets linked to persisted
  evidence IDs.
- **4 Specialized Decision Agents** (evaluated in one structured AI pass per candidate):
    - **Balanced Hiring Manager (`balanced`)** — Weighs score, mandatory requirements, skills, and verification evenly.
    - **Strict Bar Raiser (`bar_raiser`)** — Enforces high score thresholds, strict mandatory pass, and verified proof.
    - **Growth & Potential Scout (`growth_potential`)** — Highlights strong skills, hands-on projects, and upward
      trajectory.
    - **Verification & Risk Guard (`risk_guardian`)** — Prioritizes authenticity, completeness, and clean verification
      signals.
- **Interactive Ranking UI & Filtering:** Switch Decision Agents live on the Applicant Ranking page, filter by AI
  Decision outcome (`Strong Advance`, `Advance`, `Manual Review`, `Hold`, `Do Not Advance`), view Decision Distribution
  charts, inspect historical runs by timestamp, and compare 2–4 candidates side by side.
- **Configurable Threshold & Optional Auto-Apply Mode:** Configure `min_accept_threshold` (default `65%`) in Run
  Options. Defaults to safe **human-in-the-loop** review; optionally enable `auto_apply_decisions` to automatically
  shortlist/reject with immutable `ApplicationStatusHistory` entries and candidate notifications.

### Candidate Management, Notifications & Workspace Controls

- **Candidate Notifications:** Send candidate status & feedback emails via the **SendPulse REST API** (
  `POST /api/v1/applications/{id}/notify` or the **Notify candidate** button), with an automatic safe **Audit Outbox**
  fallback when SendPulse is not configured.
- **Full Candidate & Application Lifecycle:** Manual candidate editing, soft/audit-preserving application & resume
  deletion, **Clean Delete** (`?purge=true`) in Data Explorer (removes candidate, resumes, applications, and files
  cleanly while preserving DB append-only trigger safety), and section-level **Delete All** (Jobs, Candidates, Team)
  protected by typed confirmation (`DELETE`).
- **Multi-Tenant Company & RBAC:** JWT auth + Google OAuth Sign-In, role-based access (`Admin`, `Recruiter`, `Viewer`),
  per-job access grants, Analytics dashboard, and Data Explorer.

---

## 2. System Architecture

```mermaid
flowchart LR
    subgraph Client["Web Frontend (SvelteKit 5 + Tailwind v4)"]
        UI["Recruiter Dashboard\nJobs · Upload · Ranking · Analysis · Compare · Data Explorer"]
    end

    subgraph API["Backend API & Async Workers (FastAPI + Celery)"]
        GW["FastAPI REST API (/api/v1)"]
        CW["Celery Workers + Beat\n(PDF/DOCX/OCR + Async AI)"]
    end

    subgraph Agents["Multi-Agent AI Engine (Pydantic AI + DSPy)"]
        ORCH["3-Tier Router + L1 LRU / L2 Redis Cache\nprimary: gpt-5.4 | fast: gpt-5.4-mini | nano: gpt-5.4-nano"]
        EXT["Extraction Agent\n(Resume & JD Requirements)"]
        VER["Verification & Fraud Risk Agent\n(12 Checks + 0–100 Fraud Score)"]
        ANA["Analysis & Scoring Agent\n(Weighted Engine + Plain-English Summary)"]
        DEC["4-Agent Decision Panel\n(Balanced · Bar Raiser · Growth · Risk Guard)"]
    end

    subgraph External["External Verification & Observability"]
        LLM["OpenAI GPT-5.4 Family\n+ Google Gemini Fallback"]
        BD["Bright Data SDK (LinkedIn)\nGitHub API · Safe HTML · DNS/MX"]
        OBS["LangSmith Tracing\nSentry SDK · SMTP / Audit Outbox"]
    end

    subgraph Storage["Persistence Layer"]
        PG[("PostgreSQL 16 + pgvector\nImmutable Audit & Ranking History")]
        RD[("Redis 7\nCelery Broker + Shared L2 AI Cache")]
        FS[("Resume Storage\nLocal Volume / S3")]
    end

    UI <--> GW
    GW <--> PG
    GW <--> RD
    GW --> CW
    CW <--> FS
    CW --> ORCH
    GW --> ORCH
    ORCH --> EXT --> VER --> ANA --> DEC
    ORCH <--> RD
    ORCH <--> LLM
    VER <--> BD
    ORCH -.-> OBS
    DEC --> PG
```

---

## 3. AI Agent & Optimization Pipeline

Job Sentry uses a hybrid **Pydantic AI + DSPy** runtime (`AI_ENGINE=auto`) optimized for low token cost and low latency:

| Task                            | Engine                 | Model Tier | Default Model         | Max Output Tokens | Purpose                                          |
|:--------------------------------|:-----------------------|:-----------|:----------------------|:-----------------:|:-------------------------------------------------|
| `resume_profile`                | Pydantic AI            | `primary`  | `openai:gpt-5.4`      |       4096        | High-recall structured resume extraction         |
| `job_requirements`              | Pydantic AI            | `fast`     | `openai:gpt-5.4-mini` |       2048        | Atomic JD requirement decomposition              |
| `candidate_decision_agent`      | DSPy (`Predict`/`CoT`) | `fast`     | `openai:gpt-5.4-mini` |       1200        | 4-agent hiring decision panel (1 call/candidate) |
| `linkedin_profile_verification` | DSPy (`Predict`/`CoT`) | `fast`     | `openai:gpt-5.4-mini` |       1000        | Bright Data LinkedIn vs. resume cross-check      |
| `github_profile_verification`   | DSPy (`Predict`/`CoT`) | `fast`     | `openai:gpt-5.4-mini` |        900        | GitHub repos/languages vs. resume cross-check    |
| `portfolio_ai_verification`     | DSPy (`Predict`/`CoT`) | `fast`     | `openai:gpt-5.4-mini` |        900        | Portfolio HTML vs. resume consistency            |
| `score_explanation`             | DSPy (`Predict`/`CoT`) | `fast`     | `openai:gpt-5.4-mini` |        700        | Concise plain-English recruiter summary          |
| `project_link_verification`     | DSPy (`Predict`/`CoT`) | `nano`     | `openai:gpt-5.4-nano` |        500        | Per-link project HTML consistency check          |
| `relevance_analysis`            | DSPy (`Predict`/`CoT`) | `nano`     | `openai:gpt-5.4-nano` |        500        | Grounded claim-to-requirement relevance          |

### Built-In Cost & Performance Optimizations

- **Automatic Tiered Failover:** `nano → fast → primary → fallback_models` (e.g. `google:gemini-3.6-flash`).
- **Two-Tier Content-Addressed AI Cache:** L1 in-process LRU (512 entries, ~0.2 ms hits) + L2 shared Redis cache (24h
  TTL, ~0.6 ms hits shared between FastAPI and Celery workers), keyed by
  `(task, prompt_version, engine, model, input_hash)`.
- **Bounded Reasoning Effort & Zero Double-CoT:** OpenAI GPT-5 reasoning models use `reasoning_effort="low"` +
  `dspy.Predict` (avoiding redundant CoT JSON output tokens on top of native reasoning).
- **Unchanged Peer Reuse & In-Flight Deduplication:** Re-ranking a subset or individual reuses unchanged peers'
  persisted `agent_decisions` at $0 cost, and identical `(requirement, claim)` relevance pairs are deduplicated in
  flight.
- **Concurrent Verification I/O:** Email DNS/MX, URL reachability, project links, GitHub profile, portfolio AI, and
  Bright Data LinkedIn checks execute concurrently via `asyncio.gather`.

---

## 4. Tech Stack

| Layer                       | Technologies                                                                                                                             |
|:----------------------------|:-----------------------------------------------------------------------------------------------------------------------------------------|
| **Backend API**             | Python 3.13, FastAPI, Uvicorn, SQLAlchemy 2 (Async), Alembic, Pydantic v2, Pydantic Settings                                             |
| **AI & Agents**             | Pydantic AI, DSPy 3, OpenAI (`gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano`), Google Gemini fallback, offline `heuristic` mode                |
| **Document Parsing & OCR**  | PyMuPDF (`pymupdf`), `python-docx`, Pillow, Tesseract OCR (`pytesseract`)                                                                |
| **External Verification**   | Official Bright Data Python SDK (`brightdata-sdk`), GitHub REST API, `httpx`, `dnspython`, `phonenumbers`                                |
| **Background Jobs & Cache** | Celery 5 (Worker + Beat), Redis 7 (Broker + Shared L2 AI Response Cache)                                                                 |
| **Database**                | PostgreSQL 16 with `pgvector` (`asyncpg`), append-only audit triggers                                                                    |
| **Observability & Auth**    | LangSmith Tracing (optional), Sentry SDK, Argon2id (`argon2-cffi`), PyJWT, Google OAuth                                                  |
| **Frontend**                | SvelteKit 2, Svelte 5 (Runes), TypeScript, Tailwind CSS v4, `bits-ui`, `@tanstack/svelte-table`, `layerchart`, Lucide Icons, Vitest, Bun |
| **Infrastructure**          | Docker & Docker Compose (7 services), Nginx reverse proxy, Cloudflare Quick/Named Tunnel (`cloudflared`)                                 |

---

## 5. Project Structure

```text
job-sentry-agy/
├── backend/
│   ├── app/
│   │   ├── ai_features/
│   │   │   ├── ai/                  # Engine router, 3-tier settings, DSPy runner, L1/L2 cache, LangSmith tracing
│   │   │   ├── models/              # Candidate, Application, Resume, ExtractedProfile, ScoreExplanation
│   │   │   ├── resumes/             # PDF/DOCX/OCR parsers, grounding, Celery worker & beat tasks
│   │   │   └── schemas/             # Extraction, requirement, verification & decision Pydantic schemas
│   │   ├── core/                    # Config, async DB session, JWT/Argon2 security, Sentry observability
│   │   ├── models/                  # User, Company, Job, JobRequirement, JobAccess, Token
│   │   └── modules/
│   │       ├── auth/                # Login, Register, Refresh, Google OAuth
│   │       ├── companies/           # Multi-tenant company & team management
│   │       ├── jobs/                # Job CRUD, lifecycle, requirements, weights, job access
│   │       ├── candidate_intelligence/
│   │       │   ├── api/             # /verify, /analysis, /rank, /ranking, /compare, /decision-agents, /notify
│   │       │   ├── evidence/        # Exact/alias/semantic/LLM/GitHub evidence matchers & providers
│   │       │   ├── ranking/         # Deterministic ranker + 4-Agent Decision Panel
│   │       │   ├── scoring/         # Category weighted formulas & mandatory gates
│   │       │   ├── verification/    # 12 checks (DNS/MX, authenticity, Bright Data LinkedIn, GitHub, HTML AI)
│   │       │   └── notifications.py # SMTP + Audit Outbox candidate notification dispatcher
│   │       ├── application_status/  # Immutable status transitions & history
│   │       ├── analytics/           # Hiring funnel & score analytics
│   │       └── health/              # /health and /ready probes
│   ├── migrations/                  # Alembic PostgreSQL migrations
│   ├── tests/                       # 93 backend unit, contract & simulation tests (pytest)
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── lib/
│   │   │   ├── components/          # CandidateProfile, RequirementsPanel, ScoreRing, Donut, ConfirmDialog, UI
│   │   │   ├── services/            # Typed API clients (jobs, applications, resumes, directory, analytics, auth)
│   │   │   ├── stores/              # Toast, confirm dialog, dynamic page titles
│   │   │   └── types/               # TypeScript contracts (Analysis, RankingPage, AgentDecision, FraudRisk)
│   │   └── routes/(app)/            # Dashboard, Jobs, Upload, Applicants Ranking, Analysis, Compare, Candidates, Data Explorer, Analytics, Company, Settings
│   ├── tests/                       # 36 frontend Vitest tests
│   ├── Dockerfile
│   └── package.json
├── info/                            # Detailed architecture docs, API specs, audit & phase notes
├── job-sentry-zeroth-review.pptx    # Aligned project review presentation
├── docker-compose.yml               # Single-command 7-service stack
└── README.md                        # This file
```

---

## 6. Quick Start with Docker Compose (Recommended)

Requires only **Docker** and **Docker Compose**.

### Step 1: Prepare Environment Files

```bash
cp -n backend/.env.example backend/.env
cp -n frontend/.env.example frontend/.env
```

Edit `backend/.env` to add your API keys (`OPENAI_API_KEY`, optional `GOOGLE_API_KEY`, `BRIGHT_DATA_API_KEY`,
`LANGSMITH_API_KEY`, `SMTP_HOST`) — or keep `AI_MODEL=heuristic` for zero-key offline mode.

### Step 2: Build & Start All 7 Services

```bash
docker compose up --build -d
```

This launches:

1. **`db`** — PostgreSQL 16 + `pgvector` (`localhost:5433`)
2. **`redis`** — Redis 7 for Celery queues & shared L2 AI cache (`localhost:6380`)
3. **`backend`** — Runs `alembic upgrade head` automatically and starts FastAPI (`http://localhost:8000`)
4. **`celery_worker`** — Async worker (concurrency 4) for resume parsing, OCR, AI extraction & explanations
5. **`celery_beat`** — Periodic recovery scheduler for stuck resume jobs
6. **`frontend`** — SvelteKit static build served via Nginx (`http://localhost:3000`), reverse-proxying `/api/*`,
   `/health`, and `/ready` to `backend`
7. **`cloudflared`** — Optional Cloudflare Quick Tunnel generating a public `https://*.trycloudflare.com` URL

### Step 3: Verify & Open

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

- **Web App:** [http://localhost:3000](http://localhost:3000)
- **Backend API Docs (Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Public Shareable URL:** `docker compose logs cloudflared | grep -o 'https://[-a-z0-9]*\.trycloudflare.com'`

### Useful Docker Commands

```bash
docker compose ps                     # Check status of all 7 services
docker compose logs -f backend        # Tail FastAPI logs
docker compose logs -f celery_worker  # Tail Celery worker logs
docker compose down                   # Stop services (preserves DB & resume volumes)
docker compose down -v                # Stop services and wipe all volumes (fresh start)
```

---

## 7. Configuration & Environment Variables

### Backend (`backend/.env`)

| Variable                                                        | Default / Example                   | Description                                                                                |
|:----------------------------------------------------------------|:------------------------------------|:-------------------------------------------------------------------------------------------|
| `AI_ENGINE`                                                     | `auto`                              | `auto` (Pydantic AI for extraction, DSPy for reasoning), `pydantic_ai`, or `dspy`          |
| `AI_MODEL`                                                      | `openai:gpt-5.4` (or `heuristic`)   | Primary tier model (`heuristic` runs completely offline)                                   |
| `AI_FAST_MODEL`                                                 | `openai:gpt-5.4-mini`               | Fast tier for requirements, verification, explanations & Decision Agents                   |
| `AI_NANO_MODEL`                                                 | `openai:gpt-5.4-nano`               | Ultra-fast tier for relevance & project-link classification                                |
| `AI_FALLBACK_MODELS`                                            | `google:gemini-3.6-flash`           | Comma-separated fallback models                                                            |
| `AI_CACHE_ENABLED`                                              | `true`                              | Enables L1 LRU + L2 Redis content-addressed AI response cache                              |
| `AI_CACHE_TTL_SECONDS`                                          | `86400`                             | Shared Redis AI cache TTL (seconds)                                                        |
| `AI_REASONING_EFFORT_EXTRACTION` / `_REASONING`                 | `low`                               | Bounds hidden reasoning tokens on OpenAI GPT-5/o-series models                             |
| `OPENAI_API_KEY` / `GOOGLE_API_KEY` / `ANTHROPIC_API_KEY`       | *(secret)*                          | Provider API keys for configured models                                                    |
| `BRIGHT_DATA_API_KEY` (or `BRIGHTDATA_API_TOKEN`)               | *(secret)*                          | Official Bright Data SDK key for LinkedIn profile verification                             |
| `GITHUB_TOKEN`                                                  | *(optional secret)*                 | Raises GitHub REST API rate limits during profile verification                             |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | `false` / *(secret)* / `job-sentry` | Enables fire-and-forget LangSmith run tracing for all AI tasks                             |
| `SENDPULSE_API_KEY`                                             | *(optional secret)*                 | Bearer API key for SendPulse REST API (no OAuth; uses Audit Outbox when unset)             |
| `SENDPULSE_API_FROM_EMAIL`                                      | `devtest@sendpulseemail.com`        | Verified sender email (`devtest@sendpulseemail.com` is pre-verified on the SMTP Test plan) |
| `SENDPULSE_API_FROM_NAME`                                       | `Job Sentry`                        | Optional sender display name                                                               |
| `SENDPULSE_API_BASE_URL`                                        | `https://api.sendpulse.com`         | Optional SendPulse REST API base URL                                                       |
| `SENTRY_DSN`                                                    | *(optional)*                        | Enables scrubbed error reporting to Sentry                                                 |
| `JWT_SECRET`                                                    | *(32+ char secret)*                 | Signing secret for access & refresh tokens                                                 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`                     | *(optional)*                        | Enables Google Sign-In                                                                     |

### SendPulse Email Setup & Usage (No OAuth — Bearer API Key)

Job Sentry sends candidate status/feedback emails via the SendPulse REST API using
`Authorization: Bearer <SENDPULSE_API_KEY>` (`verifyAuth()` → `GET /user/info`, `sendEmail()` → `POST /smtp/emails`
in [notifications.py](backend/app/modules/candidate_intelligence/notifications.py)).

1. **Configure `backend/.env`:**
   ```env
   SENDPULSE_API_KEY=your-sendpulse-api-key
   SENDPULSE_API_FROM_EMAIL=devtest@sendpulseemail.com
   SENDPULSE_API_FROM_NAME="Job Sentry"
   SENDPULSE_API_BASE_URL=https://api.sendpulse.com
   ```
2. **Recreate the backend container** so Docker loads the updated `.env`:
   ```bash
   docker compose up -d --force-recreate backend celery_worker
   ```
3. **Verify auth & send a test email with the CLI script:**
   ```bash
   # Verify API key (GET /user/info)
   docker exec job_sentry_backend python scripts/test_sendpulse.py --verify-only

   # Send a test email (POST /smtp/emails)
   docker exec job_sentry_backend python scripts/test_sendpulse.py \
     --to recipient@example.com \
     --subject "Job Sentry Test" \
     --text "Hello from SendPulse!"
   ```
4. **Programmatic usage:**
   ```python
   from app.modules.candidate_intelligence.notifications import verifyAuth, sendEmail

   info = await verifyAuth()  # GET /user/info
   res = await sendEmail(     # POST /smtp/emails
       to_email="candidate@example.com",
       subject="Interview Invitation",
       html="<p>Hello! You have been shortlisted.</p>",
       text="Hello! You have been shortlisted.",
   )
   ```

> **SendPulse SMTP Test (Demo) Plan Notes:**
> - New SendPulse accounts start on the **SMTP Test** plan where `devtest@sendpulseemail.com` is pre-verified and active
    out of the box, so you can send test emails immediately using the default `SENDPULSE_API_FROM_EMAIL`.
> - In demo mode, SendPulse automatically overrides the visible sender to `SP test <devtest@sendpulseemail.com>` and
    prefixes the subject with `For development purposes only: ` regardless of the `from`/`subject` values sent. This is
    expected SendPulse behavior.
> - `devtest@sendpulseemail.com` is only available on the Test plan and is removed once you verify your own
    domain/sender. On Free or paid plans, set `SENDPULSE_API_FROM_EMAIL` to your own verified sender address (sending
    from an unverified sender returns HTTP `422 "Sender is not valid"`).
> - If your plan's hourly or total sending quota is reached, SendPulse returns HTTP `429`; Job Sentry surfaces a clear,
    retryable error without crashing ranking runs.

### Frontend (`frontend/.env`)

- `PUBLIC_API_BASE_URL` — Backend URL (leave empty in Docker so Nginx proxies `/api/*` automatically; use
  `http://localhost:8000` for local dev).
- `PUBLIC_GOOGLE_CLIENT_ID` — Must match backend `GOOGLE_CLIENT_ID` (leave empty to hide Google Sign-In).
- `PUBLIC_SCORE_SCALE` — `100` (0–100 display scale).

---

## 8. API Overview

All endpoints are prefixed with `/api/v1` (except `/health` and `/ready`). Full interactive OpenAPI docs are available
at `/docs`.

- **Auth & Company:** `POST /auth/register`, `POST /auth/login`, `POST /auth/google`, `POST /auth/refresh`,
  `GET/PATCH /companies/me`, `GET/POST/DELETE /companies/me/members`
- **Jobs & Requirements:** `GET/POST/DELETE /jobs`, `GET/PATCH/DELETE /jobs/{id}`,
  `POST /jobs/{id}/publish|pause|close|archive`, `GET/POST/PATCH/DELETE /jobs/{id}/requirements`,
  `POST /jobs/{id}/extract-requirements`
- **Resumes & Candidates:** `POST /jobs/{id}/resumes/upload`, `GET /resumes/{id}`, `DELETE /resumes/{id}`,
  `GET/DELETE /candidates`, `GET/PATCH/DELETE /candidates/{id}` (supports `?purge=true` clean delete),
  `DELETE /applications/{id}`
- **Intelligence, Verification, Ranking & Notifications:**
    - `POST /applications/{id}/verify` — Runs all 12 verification checks & returns `fraud_risk` (0–100)
    - `GET /applications/{id}/analysis` — Read-only analysis, evidence, verification, `fraud_risk`, AI summary, and
      4-agent decisions
    - `POST /applications/{id}/notify` — Sends (SMTP) or records (Audit Outbox) candidate outcome & feedback email
    - `GET /decision-agents` — Lists the 4 available Decision Agents
    - `POST /jobs/{id}/rank` — Executes versioned ranking run (`decision_agent`, `min_accept_threshold`,
      `auto_apply_decisions`, `force_rescore`, `force_verify`, `application_ids`)
    - `GET /jobs/{id}/ranking` — Stable paginated ranking view with `decision_agent`, `decision`, `eligibility`,
      `verification_status`, `status`, `min_score`, `max_score`, `run_id` filters
    - `GET /jobs/{id}/ranking/history` — Immutable timestamped ranking runs
    - `POST /jobs/{id}/compare` — Side-by-side comparison of 2–4 candidates
- **Analytics & Health:** `GET /analytics/*`, `GET /health`, `GET /ready`

---

## 9. Running Locally Without Docker

### Prerequisites

- PostgreSQL 16 with `pgvector` extension (`localhost:5432`)
- Redis 7 (`localhost:6379`)
- Python 3.12+ with `uv` (or `pip`), `tesseract-ocr`
- [Bun](https://bun.sh/) (or Node.js 20+)

### 1. Backend API

```bash
cd backend
uv sync
ALEMBIC_CONFIRM_DB=kiran uv run alembic upgrade head
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Celery Worker & Beat (separate terminals)

```bash
cd backend
uv run celery -A app.ai_features.resumes.celery_app:celery_app worker -Q resumes,celery -l info --concurrency 4
```

```bash
cd backend
uv run celery -A app.ai_features.resumes.celery_app:celery_app beat -l info
```

### 3. Frontend Web App

```bash
cd frontend
bun install
bun run dev   # http://localhost:5173
```

---

## 10. Testing & Verification

### Backend (93 pytest tests)

```bash
cd backend
TEST_DATABASE_URL="postgresql+asyncpg://postgres:phase4test@127.0.0.1:55432/job_sentry_test" \
  .venv/bin/pytest \
  tests/ai_features/ai/test_task_routing_and_extraction.py \
  tests/candidate_intelligence/test_project_link_verification.py \
  tests/candidate_intelligence/test_real_world_simulation.py \
  tests/candidate_intelligence/test_endpoint_contracts.py \
  tests/candidate_intelligence/test_candidate_crud_and_celery.py \
  tests/candidate_intelligence/test_verification_matrix.py -v
```

### Frontend (Typecheck + 36 Vitest tests)

```bash
cd frontend
npm run check && npm test
```

---

## 11. Cloudflare Tunnel & Production Deployment

### Cloudflare Quick Tunnel (Included in Docker Compose)

`job_sentry_cloudflared` automatically exposes both the SvelteKit UI and FastAPI `/api/*` via Nginx over a single HTTPS
URL:

```bash
# Print the live public URL
docker compose logs cloudflared | grep -o 'https://[-a-z0-9]*\.trycloudflare.com'

# Temporarily disable the tunnel
docker compose stop cloudflared && docker compose rm -f cloudflared

# Start Docker Compose without the tunnel
docker compose up --build -d --scale cloudflared=0
```

### Deploying to a VPS / Cloud Server

1. Clone the repository and configure `backend/.env` with `ENVIRONMENT=production`, `DEBUG=False`, a strong 32+
   character `JWT_SECRET`, `ALLOWED_CORS_ORIGINS=https://your-domain.com`, and your AI/verification API keys.
2. Start the stack:
   ```bash
   PUBLIC_API_BASE_URL=https://api.your-domain.com docker compose up --build -d
   ```
3. Terminate TLS in front of port `3000` (frontend) and port `8000` (backend) using Caddy, Nginx, or a Cloudflare Named
   Tunnel.

### Database Backup & Restore

```bash
# Backup
docker exec -t job_sentry_db pg_dump -U kiran -d kiran > backup.sql

# Restore
docker exec -i job_sentry_db psql -U kiran -d kiran < backup.sql
```
