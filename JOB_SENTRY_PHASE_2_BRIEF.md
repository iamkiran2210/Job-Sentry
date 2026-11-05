# Job Sentry — Phase 2 Brief

**Phase:** Recruitment Job Domain & Structured Requirements  
**Status:** Implemented  
**Backend:** FastAPI, PostgreSQL, SQLAlchemy 2.0 Async, Alembic, Pydantic v2

## Objective

Establish the company-scoped job domain and structured job requirements that can support future candidate evaluation.
Preserve Phase 1 authentication, authorization, and organization isolation.

## Scope

- Create and manage jobs within the authenticated user's company.
- Let company administrators add and remove registered company users, and share individual jobs with registered external
  users.
- Support viewer and editor permissions for explicitly shared jobs.
- Model structured job requirements as mandatory eligibility criteria or weighted preferences.
- Enforce job lifecycle transitions and validate preference weights before publishing.
- Offer optional AI-assisted extraction from a job description through a provider interface. Return validated
  suggestions for recruiter review.
- Preserve existing authentication and company membership boundaries on every endpoint.

## Data Model

### Job

Each job belongs to one company and includes:

- `id`, `company_id`, `title`, `description`
- `department`, `employment_type`, `work_mode`, `location`
- `openings`, `status`, `created_at`, `updated_at`

`employment_type` supports `full_time`, `part_time`, `contract`, `temporary`, and `intern`. `work_mode` supports
`onsite`, `hybrid`, and `remote`. New jobs start as `draft`.

### Job Requirement

Each requirement belongs to one job and includes:

- `id`, `job_id`, `category`, `name`
- `requirement_type`, `importance`, `weight`, `is_mandatory`
- `created_at`, `updated_at`

Categories are `skills`, `experience`, `education`, `certification`, `language`, `responsibility`, and `other`.
Importance is `low`, `medium`, or `high`.

Mandatory requirements use `requirement_type=mandatory`, `is_mandatory=true`, and `weight=0`. Preferred requirements use
`requirement_type=preferred`, `is_mandatory=false`, and a positive decimal weight no greater than 1. If preferred
requirements are defined, their weights must total 1 before a job can be published. The update endpoint synchronizes
`is_mandatory` and `requirement_type`; marking a requirement mandatory resets its weight to zero. Mandatory criteria
remain separate from preference weights.

## Job Lifecycle

Allowed transitions:

| Current status | Operation | Result     |
|----------------|-----------|------------|
| `draft`        | Publish   | `active`   |
| `active`       | Pause     | `paused`   |
| `active`       | Close     | `closed`   |
| `paused`       | Publish   | `active`   |
| `paused`       | Close     | `closed`   |
| `closed`       | Archive   | `archived` |

Archived jobs are terminal. Only draft jobs can be deleted. Closed and archived jobs cannot be edited.

## Access Management

Company administrators can add a registered user with no current company membership as a recruiter. The user receives
access to the company's jobs. Administrators can revoke recruiter membership; company administrators themselves cannot
be removed through this flow.

Company administrators can also grant a registered user explicit access to one job without changing that user's company
membership. `viewer` grants read access; `editor` also permits job and requirement changes and lifecycle operations.
Company members retain the existing full access to their company's jobs. Access grants can be listed, changed between
viewer/editor, and revoked. This phase adds direct access for existing accounts; it does not send invitations or create
accounts.

## API Surface

All routes require an active bearer-authenticated user. Company members access their company's jobs; other users need an
explicit job grant. Requests without membership or a grant return not found.

| Method   | Endpoint                                              | Purpose                                                       |
|----------|-------------------------------------------------------|---------------------------------------------------------------|
| `POST`   | `/api/v1/jobs`                                        | Create a draft job                                            |
| `GET`    | `/api/v1/jobs`                                        | List current-company jobs                                     |
| `GET`    | `/api/v1/jobs/{job_id}`                               | Retrieve a job                                                |
| `PUT`    | `/api/v1/jobs/{job_id}`                               | Update an editable job                                        |
| `DELETE` | `/api/v1/jobs/{job_id}`                               | Delete a draft job                                            |
| `POST`   | `/api/v1/jobs/{job_id}/publish`                       | Publish or resume a job                                       |
| `POST`   | `/api/v1/jobs/{job_id}/pause`                         | Pause an active job                                           |
| `POST`   | `/api/v1/jobs/{job_id}/close`                         | Close an active or paused job                                 |
| `POST`   | `/api/v1/jobs/{job_id}/archive`                       | Archive a closed job                                          |
| `GET`    | `/api/v1/jobs/{job_id}/requirements`                  | List requirements                                             |
| `POST`   | `/api/v1/jobs/{job_id}/requirements`                  | Create a requirement                                          |
| `PUT`    | `/api/v1/jobs/{job_id}/requirements/{requirement_id}` | Update a requirement                                          |
| `DELETE` | `/api/v1/jobs/{job_id}/requirements/{requirement_id}` | Delete a requirement                                          |
| `POST`   | `/api/v1/jobs/{job_id}/extract-requirements`          | Suggest structured requirements                               |
| `GET`    | `/api/v1/jobs/{job_id}/access`                        | List access grants (company admin)                            |
| `POST`   | `/api/v1/jobs/{job_id}/access`                        | Grant viewer/editor access by registered user's email         |
| `DELETE` | `/api/v1/jobs/{job_id}/access/{user_id}`              | Revoke an explicit job grant                                  |
| `POST`   | `/api/v1/companies/me/members`                        | Add a registered user to the company                          |
| `DELETE` | `/api/v1/companies/me/members/{member_id}`            | Revoke recruiter membership                                   |
| `GET`    | `/api/v1/users/me/access`                             | Return company access and all accessible jobs in one response |

## AI-Assisted Extraction

`AI_REQUIREMENTS_PROVIDER` is optional. When set, configure it as `package.module:factory`; the factory must return an
object implementing the asynchronous `extract_requirements(description)` provider interface. With no configured
provider, extraction returns HTTP 503.

Provider output is parsed and validated against the structured requirement schema, including mandatory/preferred
consistency and preference weight totals. The endpoint returns suggestions only: it does not persist requirements,
overwrite the job description, or change job status. Recruiters review and manually create or edit requirements.

## Acceptance & Verification

- Phase 1 authentication and company isolation remain in use.
- Recruiters and admins can manage jobs within their company; cross-company access is isolated.
- Job CRUD, requirements CRUD, lifecycle rules, and weight validation are covered by tests.
- Mocked extraction tests verify valid suggestions, reject invalid provider output, and confirm suggestions do not
  modify stored jobs or requirements.
- Access tests cover company membership, job-only sharing, viewer/editor permissions, and revocation.
- Verification result: **42 backend tests passed**. The Alembic upgrade SQL was generated successfully.

## Exclusions

- Candidate or application management
- Resume upload, parsing, or OCR
- Candidate scoring, ranking, matching, or analytics
- Celery and Redis
