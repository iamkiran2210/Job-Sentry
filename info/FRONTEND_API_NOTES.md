# Job Sentry API Contract & Live Verified Shapes

This document captures ground truth observed from live backend queries (`http://localhost:8000`) and the OpenAPI spec (
`/openapi.json`).

## Ground Truth Principles

1. **Envelope Structure**: All responses are wrapped in:
   ```json
   {
     "success": boolean,
     "message": string,
     "data": T | null,
     "errors": unknown | null,
     "request_id"?: string
   }
   ```
2. **Base URL & Prefix**: Single point of configuration: `PUBLIC_API_BASE_URL` (default `http://localhost:8000`). All
   API endpoints are prefixed with `/api/v1`. Probes `/health` and `/ready` are at root.
3. **Auth & Tokens**:
    - `/auth/register` creates user and returns user data with `company_id: null`. Does NOT issue tokens. User must
      subsequently call `/auth/login`.
    - `/auth/login` returns `access_token`, `refresh_token`, `token_type`, and `user`.
    - Access token stored in memory. Refresh token in `sessionStorage`.
    - 401 triggers single refresh via `POST /auth/refresh { refresh_token }`. If refresh fails, session cleared and
      redirected to `/login`.
    - Recruiter full profile obtained via `/users/me` and `/auth/me`. Access rights obtained via `GET /users/me/access`.
4. **Company**:
    - `GET /companies/me` returns 404 when recruiter has not created or joined a company:
      `{"success": false, "message": "User does not belong to any company", "data": null, "errors": null}`
    - All main recruiter pages handle no-company gracefully via Banner/Card without breaking.
    - `POST /companies` creates company: `{ name, website?, description?, industry?, location? }`.
    - `GET /companies/me/members` lists members. `POST /companies/me/members` invites `{ email, role }`.
5. **Jobs & Requirements**:
    - `POST /jobs` creates a draft job.
    - Enums:
        - `employment_type`: `full_time`, `part_time`, `contract`, `temporary`, `intern`
        - `work_mode`: `onsite`, `hybrid`, `remote`
        - `status`: `draft`, `active`, `paused`, `closed`, `archived`
    - Job lifecycle mutations (`POST /jobs/{id}/publish`, `pause`, `close`, `archive`) return minimal shape
      `{ job_id, status }`. The frontend always re-fetches the full job object.
    - Requirements Enums:
        - `category`: `skills`, `experience`, `education`, `certification`, `language`, `responsibility`, `other`
        - `requirement_type`: `mandatory`, `preferred`
        - `importance`: `low`, `medium`, `high`
    - Weight Rules: Mandatory requirements must have `weight: 0.0` and `is_mandatory: true`. Preferred requirement
      weights must sum to exactly `1.0` before publishing is permitted.
    - AI Requirement Extraction: `POST /jobs/{id}/extract-requirements` takes `{ description }`. Returns nested data:
      `{ success, data: { success, data: { suggestions: [...] } } }`. Suggestions are NEVER auto-saved.
6. **Resumes & Candidates**:
    - `POST /jobs/{id}/resumes` receives `files` via `multipart/form-data` (single file per request via XHR for true
      upload progress).
    - Poll `GET /resumes/{id}/status` until status is `completed` or `failed`.
    - Candidate names use `full_name` with fallbacks `display_name`, `candidate_name`, `name`.
    - Scores exist only after "Run ranking" (`POST /jobs/{id}/rank`). Unscored candidates display "Pending", never 0.
    - Missing data displayed as "Not provided", never a dash.
    - Resume-derived data labelled "extracted, not independently verified".
7. **Application Lifecycle**:
    - `PATCH /applications/{id}/status` accepts `under_review`, `shortlisted`, `rejected`, `offered`, `hired`,
      `withdrawn`. Requires `X-Request-ID` UUID header.
    - Manual rejection behind confirmation Alert Dialog with optional reason.
