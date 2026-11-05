# Job Sentry — Backend (Foundation, Organizations & Job Domain)

Job Sentry is an AI-powered recruitment intelligence platform. This repository contains the foundation, authentication,
company management, and recruitment job domain, built with FastAPI, PostgreSQL, SQLAlchemy 2.0 (asynchronous with
asyncpg), Alembic, Pydantic v2, and Docker.

---

## Table of Contents

- [Current Scope](#current-scope)
- [Architecture & Tech Stack](#architecture--tech-stack)
- [Project Structure](#project-structure)
- [Environment Configuration](#environment-configuration)
- [Local Development Setup](#local-development-setup)
- [Database Migrations](#database-migrations)
- [Running the Application](#running-the-application)
- [Docker & Docker Compose](#docker--docker-compose)
- [Testing](#testing)
- [API Documentation & Endpoints](#api-documentation--endpoints)
- [Security Architecture](#security-architecture)
- [Current Limitations](#current-limitations)

---

## Current Scope

The backend currently provides the production-oriented foundation and recruitment job domain:
- Application configuration via Pydantic Settings
- Asynchronous PostgreSQL integration with SQLAlchemy 2.0 & asyncpg
- Schema migrations using Alembic
- Argon2 password hashing
- Dual-token JWT authentication (short-lived access tokens + single-use rotating persistent refresh tokens)
- Session revocation / token revocation mechanism
- Google Identity OAuth verification via Google's official library
- Role-based authorization (`admin`, `recruiter`)
- Single-organization company management with creator auto-promotion and strict data isolation
- Company-scoped job CRUD, validated status lifecycle, and mandatory/preferred structured requirements
- Admin-managed company membership and explicit viewer/editor access to individual jobs
- AI-assisted requirement extraction through an optional provider interface; suggestions require recruiter review
- Standardized API response envelopes and centralized error handling (no stack trace exposure)
- Comprehensive automated test suite with Pytest

> **Strict Scope Notice:** Candidate/application management, resume upload/parsing/OCR, candidate
> scoring/ranking/analytics, Celery, and Redis are excluded.

---

## Architecture & Tech Stack

- **Runtime:** Python 3.12+ (tested with Python 3.12, 3.13, 3.14)
- **Framework:** FastAPI
- **ASGI Server:** Uvicorn
- **Database:** PostgreSQL with `asyncpg` driver
- **ORM:** SQLAlchemy 2.0 (Asynchronous sessions)
- **Migrations:** Alembic
- **Validation & Serialization:** Pydantic v2 & Pydantic Settings
- **Password Hashing:** Argon2 (`argon2-cffi`)
- **Tokens:** PyJWT (HS256)
- **OAuth:** `google-auth` (Google Identity Token verification)
- **Testing:** Pytest, pytest-asyncio, HTTPX, aiosqlite
- **Containerization:** Docker & Docker Compose

---

## Project Structure

```
backend/
├── app/
│   ├── main.py                     # FastAPI app instance, CORS, middleware, lifespan
│   ├── core/
│   │   ├── config.py               # Centralized Pydantic Settings configuration
│   │   ├── database.py             # Async engine, sessionmaker, get_db dependency
│   │   ├── dependencies.py         # Auth, active user, role, company dependencies
│   │   ├── exceptions.py           # Custom exception classes & global handlers
│   │   └── security.py             # Argon2 hashing, JWT issue/verify, Google OAuth
│   ├── models/
│   │   ├── base.py                 # Abstract base model with UUID & UTC timestamps
│   │   ├── company.py              # Company entity model
│   │   ├── token.py                # Persistent hashed refresh token record
│   │   ├── user.py                 # User entity model (admin, recruiter)
│   │   ├── job.py                  # Company job and lifecycle state
│   │   ├── job_requirement.py      # Mandatory and weighted preference requirements
│   │   ├── job_access.py           # Explicit viewer/editor job access grants
│   │   └── __init__.py             # Model exports
│   ├── schemas/
│   │   ├── auth.py                 # Registration, login, refresh, logout schemas
│   │   ├── company.py              # Company request/response schemas
│   │   ├── job.py                  # Job, requirement, and extraction schemas
│   │   └── user.py                 # User request/response schemas
│   ├── modules/
│   │   ├── auth/
│   │   │   ├── router.py           # /api/v1/auth endpoints
│   │   │   └── service.py          # Auth business logic & token lifecycle
│   │   ├── users/
│   │   │   ├── router.py           # /api/v1/users endpoints
│   │   │   └── service.py          # User lookups and profile handling
│   │   ├── companies/
│   │   │   ├── router.py           # /api/v1/companies endpoints
│   │   │   └── service.py          # Company creation, updates, member lists
│   │   └── jobs/
│   │       ├── router.py           # Company-scoped job and requirement endpoints
│   │       ├── service.py          # Lifecycle and requirement validation
│   │       └── provider.py         # Optional extraction provider interface
│   └── utils/
│       └── responses.py            # Standardized API response formatters
├── migrations/                     # Alembic async migration environment & versions
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── a5475d55ef43_initial_phase1_models.py
│       ├── 9b1c4f6e2a71_jobs_and_requirements.py
│       ├── f2c3a01d84b7_decimal_requirement_weights.py
│       ├── 7a4d91c2e6b3_normalized_requirement_weights.py
│       └── 4c8d6f1a2e73_company_and_job_access.py
├── tests/
│   ├── conftest.py                 # Fixtures, test DB session, HTTP test client
│   ├── test_auth.py                # Auth, registration, token rotation, logout tests
│   ├── test_companies.py           # Company CRUD, permissions, multi-tenant isolation
│   ├── test_users.py               # User profile, inactive user, role validation
│   └── test_jobs.py                # Job lifecycle, requirements, sharing, extraction
├── alembic.ini                     # Alembic configuration file
├── Dockerfile                      # Container definition for FastAPI backend
├── docker-compose.yml              # Multi-container orchestration (App + Postgres)
├── .env.example                    # Template environment variables
├── pytest.ini                      # Pytest async configuration
├── requirements.txt                # Production and development dependencies
└── README.md                       # Documentation
```

---

## Environment Configuration

Create a local `.env` file from the provided `.env.example`:

```bash
cp .env.example .env
```

### Environment Variables

| Variable                      | Description                                          | Default / Example                                                  |
|:------------------------------|:-----------------------------------------------------|:-------------------------------------------------------------------|
| `APP_NAME`                    | Name of the application                              | `Job Sentry`                                                       |
| `ENVIRONMENT`                 | Environment (`development`, `production`, `test`)    | `development`                                                      |
| `DEBUG`                       | Enable debug mode                                    | `True`                                                             |
| `API_V1_PREFIX`               | Base path prefix for API endpoints                   | `/api/v1`                                                          |
| `DATABASE_URL`                | Async PostgreSQL connection string                   | `postgresql+asyncpg://postgres:postgres@localhost:5432/job_sentry` |
| `JWT_SECRET`                  | Secret key for signing JWT tokens                    | Strong random string (min 32 chars)                                |
| `JWT_ALGORITHM`               | JWT signing algorithm                                | `HS256`                                                            |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Lifetime of access tokens                            | `30`                                                               |
| `REFRESH_TOKEN_EXPIRE_DAYS`   | Lifetime of refresh tokens                           | `7`                                                                |
| `GOOGLE_CLIENT_ID`            | Google OAuth Client ID                               | `your-client-id.apps.googleusercontent.com`                        |
| `GOOGLE_CLIENT_SECRET`        | Google OAuth Client Secret                           | `your-client-secret`                                               |
| `AI_REQUIREMENTS_PROVIDER`    | Optional provider factory (`package.module:factory`) | Empty (disabled)                                                   |
| `ALLOWED_CORS_ORIGINS`        | Comma-separated allowed CORS origins                 | `http://localhost:3000,http://localhost:5173`                      |

---

## Local Development Setup

### 1. Prerequisites
- Python 3.12+
- PostgreSQL 15+ running locally (or via Docker)

### 2. Create Virtual Environment & Install Dependencies

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Database Migrations

Apply database migrations to the latest revision:

```bash
alembic upgrade head
```

To rollback a migration:

```bash
alembic downgrade -1
```

To generate a new auto-detected migration:

```bash
alembic revision --autogenerate -m "describe_changes"
```

---

## Running the Application

### Development Server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The server starts at `http://localhost:8000`.

- Health Check: `http://localhost:8000/health`
- Interactive OpenAPI / Swagger UI: `http://localhost:8000/docs`
- ReDoc API Documentation: `http://localhost:8000/redoc`

---

## Docker & Docker Compose

To start both the FastAPI backend and PostgreSQL database in containers:

```bash
cd backend
docker compose up -d --build
```

Docker Compose automatically:
1. Starts PostgreSQL with health check monitoring.
2. Applies Alembic migrations (`alembic upgrade head`).
3. Starts the FastAPI Uvicorn server on port 8000.
4. Mounts persistent volume `postgres_data`.

To stop the containers:

```bash
docker compose down
```

---

## Testing

Run the automated test suite with Pytest:

```bash
cd backend
pytest -v
```

The 42 unit and integration tests cover:
- User registration (valid, duplicate, invalid email, weak password variations)
- Authentication & Login (credentials check, Argon2 hash verification)
- JWT access tokens, expiration validation
- Persistent refresh token rotation & reuse detection (revocation)
- User logout and session invalidation
- Mocked Google Identity OAuth verification & account linking
- User profile retrieval and inactive account rejection
- Role-based authorization (`admin` vs. `recruiter`)
- Company creation, auto-promotion to administrator
- Duplicate company prevention (1 company per user rule)
- Company updates restricted to administrators
- Company member listing restricted to administrators (no sensitive hash exposure)
- Multi-company data isolation (preventing cross-company data access)
- Company-scoped job CRUD, recruiter access, and job status transitions
- Admin-managed company membership and specific-job viewer/editor grants
- Company and job access revocation and viewer edit restrictions
- Requirement validation and preferred weight totals
- Mocked AI extraction, structured output validation, and non-persistence of suggestions

---

## API Documentation & Endpoints

All endpoints use standard JSON envelopes:

### Standard Success Envelope
```json
{
  "success": true,
  "message": "User registered successfully",
  "data": {
    "id": "c0182441-2c1c-4393-a447-ca630f9d99c4",
    "name": "Rahul",
    "email": "rahul@example.com",
    "role": "recruiter",
    "auth_provider": "email",
    "is_active": true,
    "is_verified": false
  }
}
```

### Standard Error Envelope
```json
{
  "success": false,
  "message": "Invalid email or password",
  "data": null,
  "errors": null
}
```

### Endpoints Table

| Method       | Endpoint                                              | Auth     | Role                                             | Description                                                     |
|:-------------|:------------------------------------------------------|:---------|:-------------------------------------------------|:----------------------------------------------------------------|
| `GET`        | `/health`                                             | None     | Anyone                                           | Service health check                                            |
| `POST`       | `/api/v1/auth/register`                               | None     | Anyone                                           | Register user with email, name, strong password                 |
| `POST`       | `/api/v1/auth/login`                                  | None     | Anyone                                           | Authenticate with email/password, issues tokens                 |
| `POST`       | `/api/v1/auth/refresh`                                | None     | Anyone                                           | Rotate refresh token and issue new token pair                   |
| `POST`       | `/api/v1/auth/logout`                                 | Optional | Anyone                                           | Revoke persistent refresh token session                         |
| `POST`       | `/api/v1/auth/google`                                 | None     | Anyone                                           | Authenticate or register using Google ID token                  |
| `GET`        | `/api/v1/auth/me`                                     | Bearer   | Active User                                      | Get profile of currently authenticated user                     |
| `GET`        | `/api/v1/users/me`                                    | Bearer   | Active User                                      | Get current user profile                                        |
| `GET`        | `/api/v1/users/me/access`                             | Bearer   | Active User                                      | List company membership and all accessible jobs in one response |
| `GET`        | `/api/v1/users/admin/check`                           | Bearer   | Admin                                            | Admin-only role check                                           |
| `POST`       | `/api/v1/companies`                                   | Bearer   | Active User                                      | Create company, assigns creator as Admin                        |
| `GET`        | `/api/v1/companies/me`                                | Bearer   | Member                                           | Retrieve company info (Admins and Recruiters)                   |
| `PUT`        | `/api/v1/companies/me`                                | Bearer   | Admin                                            | Update company info (Admin only)                                |
| `GET`        | `/api/v1/companies/me/members`                        | Bearer   | Admin                                            | List all company members (Admin only)                           |
| `POST`       | `/api/v1/companies/me/members`                        | Bearer   | Admin                                            | Add a registered user as a company recruiter                    |
| `DELETE`     | `/api/v1/companies/me/members/{member_id}`            | Bearer   | Admin                                            | Revoke company membership                                       |
| `POST`       | `/api/v1/jobs`                                        | Bearer   | Company member                                   | Create a company-scoped draft job                               |
| `GET`        | `/api/v1/jobs`                                        | Bearer   | Company member or explicit grant                 | List company jobs and jobs shared with the user                 |
| `GET`        | `/api/v1/jobs/{job_id}`                               | Bearer   | Company member or explicit grant                 | Get an authorized job                                           |
| `PUT`        | `/api/v1/jobs/{job_id}`                               | Bearer   | Company member or editor grant                   | Update a draft, active, or paused job                           |
| `DELETE`     | `/api/v1/jobs/{job_id}`                               | Bearer   | Company member or editor grant                   | Delete a draft job                                              |
| `POST`       | `/api/v1/jobs/{job_id}/publish`                       | Bearer   | Company member or editor grant                   | Publish a draft or resume a paused job                          |
| `POST`       | `/api/v1/jobs/{job_id}/pause`                         | Bearer   | Company member or editor grant                   | Pause an active job                                             |
| `POST`       | `/api/v1/jobs/{job_id}/close`                         | Bearer   | Company member or editor grant                   | Close an active or paused job                                   |
| `POST`       | `/api/v1/jobs/{job_id}/archive`                       | Bearer   | Company member or editor grant                   | Archive a closed job                                            |
| `GET/POST`   | `/api/v1/jobs/{job_id}/requirements`                  | Bearer   | Read: member/viewer/editor; write: member/editor | List or create requirements                                     |
| `PUT/DELETE` | `/api/v1/jobs/{job_id}/requirements/{requirement_id}` | Bearer   | Company member or editor grant                   | Edit or delete a requirement                                    |
| `POST`       | `/api/v1/jobs/{job_id}/extract-requirements`          | Bearer   | Company member or explicit grant                 | Return suggestions for recruiter review                         |
| `GET`        | `/api/v1/jobs/{job_id}/access`                        | Bearer   | Company Admin                                    | List explicit job access grants                                 |
| `POST`       | `/api/v1/jobs/{job_id}/access`                        | Bearer   | Company Admin                                    | Grant registered user viewer or editor access                   |
| `DELETE`     | `/api/v1/jobs/{job_id}/access/{user_id}`              | Bearer   | Company Admin                                    | Revoke explicit job access                                      |

---

## Security Architecture

1. **Argon2 Password Hashing:** Uses `argon2-cffi` memory-hard hashing algorithm to protect against GPU-based cracking.
2. **Dual Token Flow with Rotation:**
   - Short-lived Access Tokens (30 mins) containing user ID, role, and company ID.
   - Longer-lived Refresh Tokens (7 days) stored as cryptographic SHA-256 hashes in `refresh_tokens` table.
   - Single-use rotation: using a refresh token marks it revoked and issues a new pair.
   - Token reuse detection: presenting a revoked token rejects the session.
3. **No Sensitive Data Exposure:** Password hashes and raw refresh tokens are never returned in API responses or persisted in raw form.
4. **Role-Based Access Control (RBAC):** Modular FastAPI dependencies (`require_role`, `require_company_admin`) enforce access permissions.
5. **Data Isolation:** Company membership is resolved from `current_user.company_id`. Cross-company job access requires
   an explicit grant; `viewer` grants read access and `editor` grants write access. Supplying another company's IDs
   alone never grants access.
6. **Safe Error Handling:** Centralized exception handlers catch all internal server errors and format standard 500 JSON responses without leaking tracebacks or database internals.

---

## Current Limitations

- Single company per user (multi-tenant switching is planned for later phases).
- User invitation workflows and team invitations are planned for a later phase.
- Access grants target existing registered users; email invitation and account creation flows are not included.
- Candidate/application management, resume upload/parsing, scoring, ranking, and analytics remain excluded from this
  phase.
- Extraction is disabled until `AI_REQUIREMENTS_PROVIDER` points to a configured provider factory. The endpoint returns
  suggestions only and does not save or publish them.
- Preferred requirement weights accept decimals from 0 to 1 and may be incomplete while drafting; publishing validates
  that their weights total 1.0. Mandatory requirements carry zero preference weight. Updating `is_mandatory`
  synchronizes `requirement_type` and resets the weight to zero when set to `true`.
- Job statuses transition from `draft` to `active`, `active` to `paused` or `closed`, `paused` to `active` or `closed`,
  and `closed` to `archived`. Archived jobs are terminal; only draft jobs can be deleted.
