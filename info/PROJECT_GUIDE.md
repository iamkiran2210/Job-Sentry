# Job Sentry Project Guide

This guide explains where the code lives, what the main classes do, and where to make changes. It is written for
developers and coding agents who are new to this repository.

## Start Here

- The FastAPI application is `backend/app/main.py`.
- Backend routes are grouped under `backend/app/modules/`.
- Request and response validation is in `backend/app/schemas/`.
- Database tables and relationships are in `backend/app/models/`.
- Database changes are versioned in `backend/migrations/versions/`.
- Tests are in `backend/tests/`.
- The Google OAuth playground is `sample-frontend/index.html`.

The root `main.py` is a small Python hello-world script. It does not start the API. The API starts from the `backend/`
directory with `uvicorn app.main:app --reload`.

## Repository Map

```text
.
├── README.md                       # Short project overview
├── PROJECT_GUIDE.md                # This code and architecture guide
├── JOB_SENTRY_PHASE_1_BRIEF.pdf    # Original foundation brief
├── JOB_SENTRY_PHASE_2_BRIEF.md     # Job domain and requirements brief
├── pyproject.toml                  # Root Python project metadata
├── uv.lock                         # Locked root Python dependencies
├── main.py                         # Placeholder hello-world script
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, middleware, and router registration
│   │   ├── core/                   # Settings, database, security, auth dependencies, errors
│   │   ├── models/                 # SQLAlchemy database tables
│   │   ├── schemas/                # Pydantic input and output shapes
│   │   ├── modules/                # Feature code: auth, companies, users, jobs
│   │   └── utils/                  # Shared helpers, including API response formatting
│   ├── migrations/                 # Active Alembic environment and migration history
│   │   └── versions/               # Ordered database changes
│   ├── tests/                      # Async API tests and shared fixtures
│   ├── alembic.ini                 # Points Alembic at migrations/
│   ├── requirements.txt            # Backend Python dependencies
│   ├── .env.example                # Environment variable template
│   ├── Dockerfile                  # Backend image setup
│   └── docker-compose.yml          # Local PostgreSQL and backend services
└── sample-frontend/
    ├── index.html                  # Standalone Google OAuth test page
    └── README.md                   # Playground setup instructions
```

`backend/alembic/` contains a second migration scaffold. The active configuration in `backend/alembic.ini` points to
`backend/migrations/`; add new migration revisions there.

## How an API Request Works

1. FastAPI matches the URL to a function in a module's `router.py`.
2. Pydantic validates request data using a schema from `backend/app/schemas/`.
3. Dependencies such as `get_current_active_user` authenticate the caller and provide a database session.
4. The router calls a service class in the same feature module. Services apply business rules and query or update
   SQLAlchemy models.
5. The router converts output to a response schema and wraps it with `success_response`.
6. Exceptions are converted to the standard error response by handlers in `backend/app/core/exceptions.py`.

Keep route functions focused on HTTP concerns. Put business rules and database work in services, validation in schemas,
and persistent fields in models.

## Application Startup

### `backend/app/main.py`

- `lifespan(app)`: disposes the shared database engine when the API shuts down.
- `health_check()`: returns service health at `GET /health`.
- The module creates `app`, configures CORS and exception handlers, then registers authentication, user, company, and
  job routers under the configured API prefix (normally `/api/v1`).

### Root and environment files

- `backend/app/core/config.py` defines the `Settings` class and the shared `settings` instance. Settings come from
  environment variables and `.env` files.
- `backend/.env.example` lists local configuration names. Copy it to `.env` and set real secrets locally; do not commit
  secrets.
- `backend/app/core/database.py` creates the async SQLAlchemy engine, session factory, declarative `Base`, and
  `get_db()` session dependency.
- `backend/Dockerfile` builds the backend container. `backend/docker-compose.yml` starts PostgreSQL and runs
  `alembic upgrade head` before Uvicorn.

## Feature Modules

Each API feature normally has a `router.py` and `service.py`. Routers define HTTP endpoints; services contain the rules
those endpoints use.

### Authentication: `backend/app/modules/auth/`

`router.py` exposes these endpoint functions:

- `register`: creates an email-and-password account.
- `login`: verifies credentials and returns access and refresh tokens.
- `refresh_token`: rotates a refresh token and returns a new token pair.
- `logout`: revokes the supplied refresh-token session.
- `google_auth`: validates a Google ID token and creates or signs in an account.
- `get_me`: returns the current authenticated user's profile.

`AuthService` in `service.py` implements the workflow:

- `register_user(db, request)`: checks for duplicate email, hashes the password, and creates the user.
- `login_user(db, request)`: checks email and password, then creates and stores a refresh-token hash.
- `refresh_tokens(db, refresh_token)`: checks the stored token, revokes it, and issues a replacement pair.
- `logout_user(db, refresh_token)`: revokes a matching stored refresh token when present.
- `authenticate_google(db, request)`: verifies the Google identity, links or creates the user, and issues tokens.

### Company and membership: `backend/app/modules/companies/`

`router.py` exposes company creation, current-company read/update, member listing, membership grant, and membership
revocation.

`CompaniesService` contains these methods:

- `_require_company_admin(user)`: checks that the caller belongs to a company and has the admin role.
- `create_company(db, user, request)`: creates a company and promotes its creator to admin.
- `get_user_company(db, user)`: returns the caller's company.
- `update_company(db, user, request)`: updates company details; admins only.
- `get_company_members(db, user)`: lists company members; admins only.
- `add_company_member(db, user, request)`: assigns an existing, currently unassigned account to the company as a
  recruiter.
- `remove_company_member(db, user, member_id)`: revokes recruiter membership. Company admins cannot be removed through
  this method.

Company membership is stored in `users.company_id`. A user can belong to one company at a time. Company members
currently have access to every job belonging to that company.

### Users and access overview: `backend/app/modules/users/`

`router.py` exposes the current user profile, the consolidated `GET /users/me/access` endpoint, and an admin-role check.

`UsersService` methods:

- `get_user_by_id(db, user_id)`: looks up a user or raises a not-found error.
- `get_access_overview(db, current_user)`: returns company membership plus every accessible job, its company, permission
  level, and whether access comes from company membership or a direct job grant.

The access response models are in `backend/app/schemas/user.py`: `CompanyAccessSummary`, `UserJobAccessSummary`, and
`UserAccessOverview`.

### Jobs, requirements, and sharing: `backend/app/modules/jobs/`

`router.py` defines job CRUD, lifecycle operations, requirement CRUD, AI extraction, and access-sharing endpoints. Small
helpers in the router are:

- `serialize(model, schema)`: validates an ORM object against a response schema and makes it JSON-ready.
- `change_status(action, ...)`: calls the service to apply a job lifecycle action.
- `owned_job(..., require_edit=False)`: finds a job the caller may access; can require edit permission.
- `serialize_job_access(record)`: formats a grant and the recipient's basic details.

`JobsService` in `service.py` owns the job rules:

- `get_job(db, user, job_id, require_edit=False)`: finds a job and checks company membership or a direct job grant. A
  `viewer` grant allows reading; an `editor` grant also allows changes.
- `list_jobs(db, user)`: lists company jobs and individually shared jobs.
- `create_job(db, user, request)`: creates a draft in the caller's company.
- `update_job(...)` and `delete_job(...)`: update an editable job or delete a draft, after checking edit access.
- `transition(db, user, job_id, action)`: applies publish, pause, close, or archive rules.
- `validate_weights(db, job_id)`: requires preferred requirement weights to total `1.0` before publish.
- `list_requirements(db, job)`, `create_requirement(...)`, `update_requirement(...)`, and `delete_requirement(...)`:
  manage structured requirements and keep active-job weights valid.
- `_ensure_active_weights_valid(...)`: rechecks preference weights after edits to an active job.
- `_ensure_requirements_editable(job)`: blocks requirement changes on closed and archived jobs.
- `validate_extraction(value)`: validates the provider's structured suggestions with Pydantic.
- `_require_job_company_admin(user, job)`: restricts access grant management to the job owner's company admins.
- `list_job_access(...)`, `grant_job_access(...)`, and `revoke_job_access(...)`: list, add/update, and remove explicit
  job grants.

`provider.py` defines the `RequirementExtractionProvider` interface. A provider implements
`extract_requirements(description)`. `get_requirement_extraction_provider()` loads the configured factory named by
`AI_REQUIREMENTS_PROVIDER`, or returns no provider if that setting is empty.

### API route inventory

| Module    | Routes                                                                                                                                                                                                                                                                                                                                                                                               |
|-----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Auth      | `POST /auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/google`; `GET /auth/me`                                                                                                                                                                                                                                                                                                |
| Users     | `GET /users/me`, `/users/me/access`, `/users/admin/check`                                                                                                                                                                                                                                                                                                                                            |
| Companies | `POST /companies`, `/companies/me/members`; `GET /companies/me`, `/companies/me/members`; `PUT /companies/me`; `DELETE /companies/me/members/{member_id}`                                                                                                                                                                                                                                            |
| Jobs      | `POST /jobs`, `/jobs/{job_id}/publish`, `/pause`, `/close`, `/archive`, `/requirements`, `/extract-requirements`, `/access`; `GET /jobs`, `/jobs/{job_id}`, `/jobs/{job_id}/requirements`, `/jobs/{job_id}/access`; `PUT /jobs/{job_id}`, `/jobs/{job_id}/requirements/{requirement_id}`; `DELETE /jobs/{job_id}`, `/jobs/{job_id}/requirements/{requirement_id}`, `/jobs/{job_id}/access/{user_id}` |

All routes use the configured prefix, normally `/api/v1`. The exact route summaries and request fields appear in `/docs`
while the API is running.

Router handler function names, grouped by file:

- `modules/auth/router.py`: `register`, `login`, `refresh_token`, `logout`, `google_auth`, `get_me`.
- `modules/companies/router.py`: `create_company`, `get_my_company`, `update_my_company`, `get_company_members`,
  `add_company_member`, `remove_company_member`.
- `modules/users/router.py`: `get_current_user_profile`, `get_my_access`, `check_admin_access`.
- `modules/jobs/router.py`: `create_job`, `list_jobs`, `get_job`, `update_job`, `delete_job`, `publish_job`,
  `pause_job`, `close_job`, `archive_job`, `list_requirements`, `create_requirement`, `update_requirement`,
  `delete_requirement`, `extract_requirements`, `list_job_access`, `grant_job_access`, `revoke_job_access`.

## Models and Relationships

All persistent models inherit from `BaseModel` in `models/base.py`. It supplies a UUID primary key and UTC `created_at`
and `updated_at` values. `utc_now()` returns the current UTC time.

- `User` (`models/user.py`): account name, email, password hash when using email login, role, optional company
  membership, provider, and active/verified flags. `UserRole` is `admin` or `recruiter`; `AuthProvider` is `email` or
  `google`.
- `Company` (`models/company.py`): organization details, members, and jobs.
- `RefreshToken` (`models/token.py`): stores a SHA-256 hash, expiry, revocation time, and user link. `is_revoked`
  reports whether the token has been revoked.
- `Job` (`models/job.py`): company-owned job fields and status. `JobStatus` is draft/active/paused/closed/archived;
  `EmploymentType` and `WorkMode` define allowed job values.
- `JobRequirement` (`models/job_requirement.py`): a categorized mandatory or preferred job requirement. Preferred
  weights are floats from 0 to 1 and must total 1.0 to publish; mandatory requirements have weight zero.
- `JobAccess` (`models/job_access.py`): an explicit per-job grant for a user. `JobAccessLevel` is `viewer` or `editor`.
- `models/__init__.py` imports every model so SQLAlchemy and Alembic see all tables.

Relationships: a company has users and jobs; a job has requirements and optional access grants; a user has refresh-token
records. Database foreign keys and ORM relationships define what gets removed when a parent row is deleted.

## Schemas and Validation

Schemas are Pydantic models. Request schemas reject invalid input before service methods run. Response schemas decide
which model fields are returned, helping prevent hashes and tokens from leaking.

- `schemas/auth.py`: registration, login, refresh, logout, Google login, and token response shapes.
  `UserRegisterRequest` validates name, email, and password strength.
- `schemas/company.py`: company create/update/response and company-member grant input. Company-member access is granted
  by registered email.
- `schemas/job.py`: job create/update/response; requirement create/update/response; extraction input/output; and job
  access grant/response. Validators trim names, keep `is_mandatory` aligned with `requirement_type`, constrain weights
  to 0–1, and check preferred-weight totals.
- `schemas/user.py`: private and public user responses plus the consolidated access overview models.

When adding a field, update the model, relevant request and response schemas, service behavior, migration, and tests
together.

## Shared Core and Helpers

### Authentication dependencies: `backend/app/core/dependencies.py`

- `get_current_user(...)`: reads the Bearer token, verifies it, and loads the user from the database.
- `get_current_active_user(...)`: rejects deactivated accounts.
- `require_role(*roles)`: builds a dependency that permits only the listed roles.
- `require_company_membership(...)`: requires a company membership.
- `require_company_admin(...)`: requires company membership and the admin role.

### Security helpers: `backend/app/core/security.py`

- `hash_password()` / `verify_password()`: create and check Argon2 password hashes.
- `hash_token()`: creates the SHA-256 digest stored for refresh tokens.
- `create_access_token()` / `create_refresh_token()`: create signed JWTs with distinct token types and expiry times.
- `decode_token()`: verifies a JWT signature and expiry.
- `verify_google_id_token()`: validates a Google ID token with Google's authentication library.

### Errors and responses

- `core/exceptions.py` defines `AppException` and common HTTP error subclasses. Its handlers convert application, HTTP,
  validation, and unexpected errors into the common JSON error shape.
- `utils/responses.py` defines `ApiResponse`, `success_response(...)`, and `error_response(...)`. API endpoints should
  use these helpers so responses have a consistent envelope.

## Database Migrations

`backend/alembic.ini` points to `backend/migrations/`. `backend/migrations/env.py` imports the model registry and uses
`Base.metadata` for Alembic.

Current revision history, oldest to newest:

1. `a5475d55ef43_initial_phase1_models.py`: companies, users, and refresh tokens.
2. `9b1c4f6e2a71_jobs_and_requirements.py`: jobs and requirements.
3. `f2c3a01d84b7_decimal_requirement_weights.py`: changes requirement weights to floating point.
4. `7a4d91c2e6b3_normalized_requirement_weights.py`: scales weights to 0–1 and adds a database check.
5. `4c8d6f1a2e73_company_and_job_access.py`: adds explicit job access grants.

Create a revision from `backend/` and review it before applying:

```bash
alembic revision --autogenerate -m "short_description"
alembic upgrade head
```

Each migration has `upgrade()` and `downgrade()` functions. Keep changes reversible where possible and ensure new tables
are imported through `app/models/__init__.py` before autogenerating.

## Tests and Local Development

`backend/tests/conftest.py` provides:

- `db_session`: creates a fresh async SQLite database per test by default.
- `client`: an HTTPX client connected to the FastAPI app with the database dependency replaced by the test session.
- `registered_user`, `auth_headers`, `company_with_admin`, and `admin_headers`: reusable user/company fixtures and
  authentication headers.

Test files are grouped by feature: `test_auth.py`, `test_companies.py`, `test_users.py`, and `test_jobs.py`. Tests
should verify success cases, validation failures, permission boundaries, and cross-company isolation for new features.

Typical local commands:

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
uvicorn app.main:app --reload
pytest -q
```

## Sample Frontend

`sample-frontend/index.html` is a standalone HTML/CSS/JavaScript Google OAuth playground, not the planned SvelteKit
frontend. It can initialize Google Identity Services, show/copy the Google ID token, exchange it with the backend,
inspect `/auth/me`, test refresh-token rotation, and log out.

Its JavaScript helpers are `log`, `clearLogs`, `setBadge`, `enableSessionButtons`, `setGoogleIdToken`,
`toggleGoogleIdToken`, `copyGoogleIdToken`, `checkBackendHealth`, `initGoogleAuth`, `handleGoogleCredentialResponse`,
`testMeEndpoint`, `testRefreshEndpoint`, and `testLogoutEndpoint`.

## Notes for Contributors and Agents

- Read the existing feature module before adding a new one; follow its router/schema/service/model pattern.
- Scope every company-owned query using the authenticated user's company or a verified explicit job grant. Never trust a
  company or user ID supplied by the caller alone.
- Company access is granted to existing accounts by company admins. Individual job grants are managed by the owning
  company's admins; viewers can read and editors can change the job.
- Add or change a database column through Alembic; do not rely on `create_all()` outside tests.
- Add tests beside the feature tests and keep API output free of password hashes, raw refresh tokens, and stack traces.
- Keep the boundaries in the Phase 2 brief: this code does not manage candidates or applications, parse resumes, or
  score/rank candidates.
