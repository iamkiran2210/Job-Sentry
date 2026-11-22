# API endpoint reference

Generated from `app.openapi()` by `scripts/export_endpoint_markdown.py`.
Request and response schemas reflect the current OpenAPI document. UUIDs, enum values, nullability, and required fields
are included in the schemas below.

## `GET /api/v1/analytics/candidates`

**Summary:** Read aggregate score and verification distributions  
**Operation ID:** `candidates_api_v1_analytics_candidates_get`  
**Tags:** Analytics

### Request

Parameters:

- `query date_from` — optional; schema
  `{"anyOf": [{"format": "date", "type": "string"}, {"type": "null"}], "title": "Date From"}`
- `query date_to` — optional; schema
  `{"anyOf": [{"format": "date", "type": "string"}, {"type": "null"}], "title": "Date To"}`
- `query job_id` — optional; schema
  `{"anyOf": [{"format": "uuid", "type": "string"}, {"type": "null"}], "title": "Job Id"}`
- `query company_id` — optional; schema
  `{"anyOf": [{"format": "uuid", "type": "string"}, {"type": "null"}], "title": "Company Id"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{
  "additionalProperties": true,
  "title": "Response Candidates Api V1 Analytics Candidates Get",
  "type": "object"
}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/analytics/jobs`

**Summary:** List company jobs with SQL applicant aggregates  
**Operation ID:** `jobs_api_v1_analytics_jobs_get`  
**Tags:** Analytics

### Request

Parameters:

- `query date_from` — optional; schema
  `{"anyOf": [{"format": "date", "type": "string"}, {"type": "null"}], "title": "Date From"}`
- `query date_to` — optional; schema
  `{"anyOf": [{"format": "date", "type": "string"}, {"type": "null"}], "title": "Date To"}`
- `query job_id` — optional; schema
  `{"anyOf": [{"format": "uuid", "type": "string"}, {"type": "null"}], "title": "Job Id"}`
- `query company_id` — optional; schema
  `{"anyOf": [{"format": "uuid", "type": "string"}, {"type": "null"}], "title": "Company Id"}`
- `query page` — optional; schema `{"default": 1, "minimum": 1, "title": "Page", "type": "integer"}`
- `query page_size` — optional; schema
  `{"default": 20, "maximum": 100, "minimum": 1, "title": "Page Size", "type": "integer"}`
- `query sort` — optional; schema `{"default": "-created_at", "title": "Sort", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{
  "additionalProperties": true,
  "title": "Response Jobs Api V1 Analytics Jobs Get",
  "type": "object"
}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/analytics/overview`

**Summary:** Read company recruitment KPIs and applicant trend  
**Operation ID:** `overview_api_v1_analytics_overview_get`  
**Tags:** Analytics

### Request

Parameters:

- `query date_from` — optional; schema
  `{"anyOf": [{"format": "date", "type": "string"}, {"type": "null"}], "title": "Date From"}`
- `query date_to` — optional; schema
  `{"anyOf": [{"format": "date", "type": "string"}, {"type": "null"}], "title": "Date To"}`
- `query job_id` — optional; schema
  `{"anyOf": [{"format": "uuid", "type": "string"}, {"type": "null"}], "title": "Job Id"}`
- `query company_id` — optional; schema
  `{"anyOf": [{"format": "uuid", "type": "string"}, {"type": "null"}], "title": "Company Id"}`
- `query interval` — optional; schema
  `{"default": "week", "enum": ["day", "week", "month"], "title": "Interval", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{
  "additionalProperties": true,
  "title": "Response Overview Api V1 Analytics Overview Get",
  "type": "object"
}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/analytics/pipeline`

**Summary:** Read status funnel and resume processing outcomes  
**Operation ID:** `pipeline_api_v1_analytics_pipeline_get`  
**Tags:** Analytics

### Request

Parameters:

- `query date_from` — optional; schema
  `{"anyOf": [{"format": "date", "type": "string"}, {"type": "null"}], "title": "Date From"}`
- `query date_to` — optional; schema
  `{"anyOf": [{"format": "date", "type": "string"}, {"type": "null"}], "title": "Date To"}`
- `query job_id` — optional; schema
  `{"anyOf": [{"format": "uuid", "type": "string"}, {"type": "null"}], "title": "Job Id"}`
- `query company_id` — optional; schema
  `{"anyOf": [{"format": "uuid", "type": "string"}, {"type": "null"}], "title": "Company Id"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{
  "additionalProperties": true,
  "title": "Response Pipeline Api V1 Analytics Pipeline Get",
  "type": "object"
}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/analytics/skills`

**Summary:** Read aggregate candidate and requirement skill coverage  
**Operation ID:** `skills_api_v1_analytics_skills_get`  
**Tags:** Analytics

### Request

Parameters:

- `query date_from` — optional; schema
  `{"anyOf": [{"format": "date", "type": "string"}, {"type": "null"}], "title": "Date From"}`
- `query date_to` — optional; schema
  `{"anyOf": [{"format": "date", "type": "string"}, {"type": "null"}], "title": "Date To"}`
- `query job_id` — optional; schema
  `{"anyOf": [{"format": "uuid", "type": "string"}, {"type": "null"}], "title": "Job Id"}`
- `query company_id` — optional; schema
  `{"anyOf": [{"format": "uuid", "type": "string"}, {"type": "null"}], "title": "Company Id"}`
- `query limit` — optional; schema `{"default": 20, "maximum": 100, "minimum": 1, "title": "Limit", "type": "integer"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{
  "additionalProperties": true,
  "title": "Response Skills Api V1 Analytics Skills Get",
  "type": "object"
}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/applications/{application_id}`

**Summary:** Application with its resume(s) and extracted profile  
**Operation ID:** `get_application_api_v1_applications__application_id__get`  
**Tags:** Resumes

### Request

Parameters:

- `path application_id` — required; schema `{"format": "uuid", "title": "Application Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/applications/{application_id}/analysis`

**Summary:** Read deterministic candidate analysis  
**Operation ID:** `analyze_application_api_v1_applications__application_id__analysis_get`  
**Tags:** Candidate Intelligence

### Request

Parameters:

- `path application_id` — required; schema `{"format": "uuid", "title": "Application Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/ApiResponse_AnalysisData_"
}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `PATCH /api/v1/applications/{application_id}/status`

**Summary:** Change application status  
**Operation ID:** `change_application_status_api_v1_applications__application_id__status_patch`  
**Tags:** Applications

Applies an authorized recruiter status transition and records immutable history.

### Request

Parameters:

- `path application_id` — required; schema `{"format": "uuid", "title": "Application Id", "type": "string"}`
- `header X-Request-ID` — optional; schema
  `{"anyOf": [{"format": "uuid", "type": "string"}, {"type": "null"}], "title": "X-Request-Id"}`

Request body: required

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/ApplicationStatusPatch"
}
```

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/applications/{application_id}/status-history`

**Summary:** List application status history  
**Operation ID:** `application_status_history_api_v1_applications__application_id__status_history_get`  
**Tags:** Applications

Returns status transitions newest first for an accessible application.

### Request

Parameters:

- `path application_id` — required; schema `{"format": "uuid", "title": "Application Id", "type": "string"}`
- `query page` — optional; schema `{"default": 1, "minimum": 1, "title": "Page", "type": "integer"}`
- `query page_size` — optional; schema
  `{"default": 20, "maximum": 100, "minimum": 1, "title": "Page Size", "type": "integer"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/ApplicationStatusPage"
}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/applications/{application_id}/verify`

**Summary:** Run deterministic verification signals  
**Operation ID:** `verify_application_api_v1_applications__application_id__verify_post`  
**Tags:** Candidate Intelligence

### Request

Parameters:

- `path application_id` — required; schema `{"format": "uuid", "title": "Application Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/ApiResponse_VerifyData_"
}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/auth/google`

**Summary:** Google OAuth login / registration  
**Operation ID:** `google_auth_api_v1_auth_google_post`  
**Tags:** Authentication

Authenticates with a verified Google ID token from frontend.

### Request

Request body: required

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/GoogleOAuthRequest"
}
```

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/auth/login`

**Summary:** User login  
**Operation ID:** `login_api_v1_auth_login_post`  
**Tags:** Authentication

Authenticates user credentials and returns JWT access and refresh tokens.

### Request

Request body: required

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/UserLoginRequest"
}
```

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/auth/logout`

**Summary:** Logout user  
**Operation ID:** `logout_api_v1_auth_logout_post`  
**Tags:** Authentication

Revokes the persistent refresh token, terminating the active session.

### Request

Request body: required

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/LogoutRequest"
}
```

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/auth/me`

**Summary:** Get current authenticated user  
**Operation ID:** `get_me_api_v1_auth_me_get`  
**Tags:** Authentication

Returns profile information for the authenticated user.

### Request

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

## `POST /api/v1/auth/refresh`

**Summary:** Refresh access token  
**Operation ID:** `refresh_token_api_v1_auth_refresh_post`  
**Tags:** Authentication

Rotates refresh token and issues a new access token.

### Request

Request body: required

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/RefreshTokenRequest"
}
```

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/auth/register`

**Summary:** Register a new user  
**Operation ID:** `register_api_v1_auth_register_post`  
**Tags:** Authentication

Registers a new user with name, email, and strong password.

### Request

Request body: required

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/UserRegisterRequest"
}
```

### Responses

#### `201` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/candidates/{candidate_id}`

**Summary:** Candidate with applications, latest extracted profile and identity-review hints  
**Operation ID:** `get_candidate_api_v1_candidates__candidate_id__get`  
**Tags:** Candidates

### Request

Parameters:

- `path candidate_id` — required; schema `{"format": "uuid", "title": "Candidate Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/companies`

**Summary:** Create a new company  
**Operation ID:** `create_company_api_v1_companies_post`  
**Tags:** Companies

Creates a company organization and assigns the creator as administrator.

### Request

Request body: required

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/CompanyCreateRequest"
}
```

### Responses

#### `201` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/companies/me`

**Summary:** Get current user company  
**Operation ID:** `get_my_company_api_v1_companies_me_get`  
**Tags:** Companies

Returns company information for the authenticated user (recruiters and admins).

### Request

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

## `PUT /api/v1/companies/me`

**Summary:** Update current company  
**Operation ID:** `update_my_company_api_v1_companies_me_put`  
**Tags:** Companies

Updates company information. Restricted to company administrators.

### Request

Request body: required

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/CompanyUpdateRequest"
}
```

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/companies/me/members`

**Summary:** List company members  
**Operation ID:** `get_company_members_api_v1_companies_me_members_get`  
**Tags:** Companies

Returns all users belonging to the company. Restricted to company administrators.

### Request

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

## `POST /api/v1/companies/me/members`

**Summary:** Grant company access  
**Operation ID:** `add_company_member_api_v1_companies_me_members_post`  
**Tags:** Companies

Adds an existing registered user as a recruiter in the current company.

### Request

Request body: required

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/CompanyMemberGrantRequest"
}
```

### Responses

#### `201` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `DELETE /api/v1/companies/me/members/{member_id}`

**Summary:** Revoke company access  
**Operation ID:** `remove_company_member_api_v1_companies_me_members__member_id__delete`  
**Tags:** Companies

Removes a recruiter from the current company.

### Request

Parameters:

- `path member_id` — required; schema `{"format": "uuid", "title": "Member Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/jobs`

**Summary:** List company jobs  
**Operation ID:** `list_jobs_api_v1_jobs_get`  
**Tags:** Jobs

Returns jobs belonging to the authenticated user's company.

### Request

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

## `POST /api/v1/jobs`

**Summary:** Create a new job  
**Operation ID:** `create_job_api_v1_jobs_post`  
**Tags:** Jobs

Creates a draft job for the authenticated user's company.

### Request

Request body: required

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/JobCreateRequest"
}
```

### Responses

#### `201` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `DELETE /api/v1/jobs/{job_id}`

**Summary:** Delete a draft job  
**Operation ID:** `delete_job_api_v1_jobs__job_id__delete`  
**Tags:** Jobs

Deletes a draft job belonging to the authenticated user's company.

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/jobs/{job_id}`

**Summary:** Get a job  
**Operation ID:** `get_job_api_v1_jobs__job_id__get`  
**Tags:** Jobs

Returns a job belonging to the authenticated user's company.

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `PUT /api/v1/jobs/{job_id}`

**Summary:** Update a job  
**Operation ID:** `update_job_api_v1_jobs__job_id__put`  
**Tags:** Jobs

Updates an editable job belonging to the authenticated user's company.

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`

Request body: required

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/JobUpdateRequest"
}
```

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/jobs/{job_id}/access`

**Summary:** List job access grants  
**Operation ID:** `list_job_access_api_v1_jobs__job_id__access_get`  
**Tags:** Jobs

Lists users granted access to a job. Restricted to the job's company administrators.

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/jobs/{job_id}/access`

**Summary:** Grant job access  
**Operation ID:** `grant_job_access_api_v1_jobs__job_id__access_post`  
**Tags:** Jobs

Grants a registered user viewer or editor access to this job.

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`

Request body: required

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/JobAccessGrantRequest"
}
```

### Responses

#### `201` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `DELETE /api/v1/jobs/{job_id}/access/{user_id}`

**Summary:** Revoke job access  
**Operation ID:** `revoke_job_access_api_v1_jobs__job_id__access__user_id__delete`  
**Tags:** Jobs

Revokes an explicit access grant to this job.

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`
- `path user_id` — required; schema `{"format": "uuid", "title": "User Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/jobs/{job_id}/applicants`

**Summary:** List applicants for a specific job (requires company membership or job access grant)  
**Operation ID:** `list_job_applicants_api_v1_jobs__job_id__applicants_get`  
**Tags:** Candidates

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`
- `query status` — optional; schema
  `{"anyOf": [{"enum": ["applied", "processing", "analyzed", "shortlisted", "rejected", "withdrawn"], "type": "string"}, {"type": "null"}], "description": "Filter applicants by application status", "title": "Status"}`;
  Filter applicants by application status

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/jobs/{job_id}/archive`

**Summary:** Archive a job  
**Operation ID:** `archive_job_api_v1_jobs__job_id__archive_post`  
**Tags:** Jobs

Archives a closed job belonging to the authenticated user's company.

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/jobs/{job_id}/close`

**Summary:** Close a job  
**Operation ID:** `close_job_api_v1_jobs__job_id__close_post`  
**Tags:** Jobs

Closes an active or paused job belonging to the authenticated user's company.

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/jobs/{job_id}/compare`

**Summary:** Compare persisted evidence for applications in one job  
**Operation ID:** `compare_job_applications_api_v1_jobs__job_id__compare_post`  
**Tags:** Candidate Intelligence

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`

Request body: required

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/CompareRequest"
}
```

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/ApiResponse_ComparisonData_"
}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/jobs/{job_id}/extract-requirements`

**Summary:** Extract requirement suggestions  
**Operation ID:** `extract_requirements_api_v1_jobs__job_id__extract_requirements_post`  
**Tags:** Jobs

Returns validated AI-assisted suggestions for recruiter review without saving them.

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`

Request body: required

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/RequirementExtractionRequest"
}
```

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/jobs/{job_id}/pause`

**Summary:** Pause a job  
**Operation ID:** `pause_job_api_v1_jobs__job_id__pause_post`  
**Tags:** Jobs

Pauses an active job belonging to the authenticated user's company.

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/jobs/{job_id}/publish`

**Summary:** Publish a job  
**Operation ID:** `publish_job_api_v1_jobs__job_id__publish_post`  
**Tags:** Jobs

Publishes a draft job or resumes a paused job after validating preference weights.

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/jobs/{job_id}/rank`

**Summary:** Create a versioned ranking run for one job  
**Operation ID:** `rank_job_api_v1_jobs__job_id__rank_post`  
**Tags:** Candidate Intelligence

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`

Request body: optional

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/RankRequest",
  "default": {
    "force_rescore": false,
    "limit": 50,
    "offset": 0
  }
}
```

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/ApiResponse_RankData_"
}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/jobs/{job_id}/ranking`

**Summary:** Read a stable page from a ranking run  
**Operation ID:** `get_ranking_api_v1_jobs__job_id__ranking_get`  
**Tags:** Candidate Intelligence

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`
- `query page` — optional; schema `{"default": 1, "minimum": 1, "title": "Page", "type": "integer"}`
- `query page_size` — optional; schema
  `{"default": 50, "maximum": 100, "minimum": 1, "title": "Page Size", "type": "integer"}`
- `query offset` — optional; schema
  `{"anyOf": [{"minimum": 0, "type": "integer"}, {"type": "null"}], "title": "Offset"}`
- `query limit` — optional; schema
  `{"anyOf": [{"maximum": 100, "minimum": 1, "type": "integer"}, {"type": "null"}], "title": "Limit"}`
- `query run_id` — optional; schema
  `{"anyOf": [{"format": "uuid", "type": "string"}, {"type": "null"}], "title": "Run Id"}`
- `query eligibility` — optional; schema
  `{"anyOf": [{"enum": ["eligible", "needs_review", "potentially_ineligible"], "type": "string"}, {"type": "null"}], "title": "Eligibility"}`
- `query verification_status` — optional; schema
  `{"anyOf": [{"enum": ["passed", "needs_review", "not_verified", "failed"], "type": "string"}, {"type": "null"}], "title": "Verification Status"}`
- `query min_score` — optional; schema
  `{"anyOf": [{"maximum": 100, "minimum": 0, "type": "number"}, {"type": "null"}], "title": "Min Score"}`
- `query max_score` — optional; schema
  `{"anyOf": [{"maximum": 100, "minimum": 0, "type": "number"}, {"type": "null"}], "title": "Max Score"}`
- `query status` — optional; schema `{"anyOf": [{"type": "string"}, {"type": "null"}], "title": "Status"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/ApiResponse_RankingPage_"
}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/jobs/{job_id}/ranking/history`

**Summary:** List immutable ranking runs  
**Operation ID:** `ranking_history_api_v1_jobs__job_id__ranking_history_get`  
**Tags:** Candidate Intelligence

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`
- `query offset` — optional; schema `{"default": 0, "minimum": 0, "title": "Offset", "type": "integer"}`
- `query limit` — optional; schema `{"default": 50, "maximum": 200, "minimum": 1, "title": "Limit", "type": "integer"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/ApiResponse_RankingHistoryPage_"
}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/jobs/{job_id}/requirements`

**Summary:** List job requirements  
**Operation ID:** `list_requirements_api_v1_jobs__job_id__requirements_get`  
**Tags:** Jobs

Returns structured requirements for a job in the authenticated user's company.

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/jobs/{job_id}/requirements`

**Summary:** Create a job requirement  
**Operation ID:** `create_requirement_api_v1_jobs__job_id__requirements_post`  
**Tags:** Jobs

Adds a validated mandatory or preferred requirement to a company job.

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`

Request body: required

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/JobRequirementCreateRequest"
}
```

### Responses

#### `201` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `DELETE /api/v1/jobs/{job_id}/requirements/{requirement_id}`

**Summary:** Delete a job requirement  
**Operation ID:** `delete_requirement_api_v1_jobs__job_id__requirements__requirement_id__delete`  
**Tags:** Jobs

Deletes a requirement belonging to a job in the authenticated user's company.

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`
- `path requirement_id` — required; schema `{"format": "uuid", "title": "Requirement Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `PUT /api/v1/jobs/{job_id}/requirements/{requirement_id}`

**Summary:** Update a job requirement  
**Operation ID:** `update_requirement_api_v1_jobs__job_id__requirements__requirement_id__put`  
**Tags:** Jobs

Updates a requirement belonging to a job in the authenticated user's company.

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`
- `path requirement_id` — required; schema `{"format": "uuid", "title": "Requirement Id", "type": "string"}`

Request body: required

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/JobRequirementUpdateRequest"
}
```

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/jobs/{job_id}/resumes`

**Summary:** Upload one or more resumes (PDF, DOCX, JPEG, PNG); processing is asynchronous  
**Operation ID:** `upload_resumes_api_v1_jobs__job_id__resumes_post`  
**Tags:** Resumes

### Request

Parameters:

- `path job_id` — required; schema `{"format": "uuid", "title": "Job Id", "type": "string"}`

Request body: required

Content-Type: `multipart/form-data`

```json
{
  "$ref": "#/components/schemas/Body_upload_resumes_api_v1_jobs__job_id__resumes_post"
}
```

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/resumes/{resume_id}`

**Summary:** Resume metadata and extracted profile (once completed)  
**Operation ID:** `get_resume_api_v1_resumes__resume_id__get`  
**Tags:** Resumes

### Request

Parameters:

- `path resume_id` — required; schema `{"format": "uuid", "title": "Resume Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `POST /api/v1/resumes/{resume_id}/retry`

**Summary:** Re-queue a failed (or never-queued) resume; needs edit access  
**Operation ID:** `retry_resume_api_v1_resumes__resume_id__retry_post`  
**Tags:** Resumes

### Request

Parameters:

- `path resume_id` — required; schema `{"format": "uuid", "title": "Resume Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/resumes/{resume_id}/status`

**Summary:** Processing status of a resume  
**Operation ID:** `get_resume_status_api_v1_resumes__resume_id__status_get`  
**Tags:** Resumes

### Request

Parameters:

- `path resume_id` — required; schema `{"format": "uuid", "title": "Resume Id", "type": "string"}`

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

#### `422` — Validation Error

Content-Type: `application/json`

```json
{
  "$ref": "#/components/schemas/HTTPValidationError"
}
```

## `GET /api/v1/users/admin/check`

**Summary:** Admin role validation check  
**Operation ID:** `check_admin_access_api_v1_users_admin_check_get`  
**Tags:** Users

Endpoint accessible only to administrators, used to verify role authorization.

### Request

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

## `GET /api/v1/users/me`

**Summary:** Get current user  
**Operation ID:** `get_current_user_profile_api_v1_users_me_get`  
**Tags:** Users

Returns profile of the currently authenticated user.

### Request

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

## `GET /api/v1/users/me/access`

**Summary:** List my access  
**Operation ID:** `get_my_access_api_v1_users_me_access_get`  
**Tags:** Users

Returns the current user's company membership and all accessible jobs with their access source and level.

### Request

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

## `GET /health`

**Summary:** Check API liveness  
**Operation ID:** `health_health_get`  
**Tags:** Health

### Request

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

## `GET /ready`

**Summary:** Check API dependencies and worker readiness  
**Operation ID:** `ready_ready_get`  
**Tags:** Health

### Request

No request body.

### Responses

#### `200` — Successful Response

Content-Type: `application/json`

```json
{}
```

## Referenced schema components

### `ApiResponse_AnalysisData_`

```json
{
  "properties": {
    "data": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/AnalysisData"
        },
        {
          "type": "null"
        }
      ]
    },
    "errors": {
      "anyOf": [
        {},
        {
          "type": "null"
        }
      ],
      "title": "Errors"
    },
    "message": {
      "title": "Message",
      "type": "string"
    },
    "success": {
      "title": "Success",
      "type": "boolean"
    }
  },
  "required": [
    "success",
    "message"
  ],
  "title": "ApiResponse[AnalysisData]",
  "type": "object"
}
```

### `AnalysisData`

```json
{
  "properties": {
    "algorithm_version": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Algorithm Version"
    },
    "analysis_summary": {
      "additionalProperties": {
        "type": "string"
      },
      "title": "Analysis Summary",
      "type": "object"
    },
    "application": {
      "$ref": "#/components/schemas/ApplicationDetail"
    },
    "application_id": {
      "format": "uuid",
      "title": "Application Id",
      "type": "string"
    },
    "candidate": {
      "$ref": "#/components/schemas/CandidateDetail"
    },
    "categories": {
      "additionalProperties": {
        "$ref": "#/components/schemas/CategoryAnalysis"
      },
      "title": "Categories",
      "type": "object"
    },
    "config_snapshot": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "type": "null"
        }
      ],
      "title": "Config Snapshot"
    },
    "data_completeness": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "title": "Data Completeness"
    },
    "eligibility": {
      "anyOf": [
        {
          "enum": [
            "eligible",
            "needs_review",
            "potentially_ineligible"
          ],
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Eligibility"
    },
    "evidence": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "title": "Evidence",
      "type": "array"
    },
    "evidence_groups": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "title": "Evidence Groups",
      "type": "array"
    },
    "explanation": {
      "$ref": "#/components/schemas/ExplanationDetail"
    },
    "mandatory_results": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "title": "Mandatory Results",
      "type": "array"
    },
    "resume": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/ResumeDetail"
        },
        {
          "type": "null"
        }
      ]
    },
    "review_signals": {
      "items": {
        "type": "string"
      },
      "title": "Review Signals",
      "type": "array"
    },
    "score": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "title": "Score"
    },
    "score_detail": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/ScoreDetail"
        },
        {
          "type": "null"
        }
      ]
    },
    "score_id": {
      "anyOf": [
        {
          "format": "uuid",
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Score Id"
    },
    "score_lower_bound": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "title": "Score Lower Bound"
    },
    "score_percent": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "title": "Score Percent"
    },
    "score_upper_bound": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "title": "Score Upper Bound"
    },
    "scoring_version": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Scoring Version"
    },
    "status_note": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Status Note"
    },
    "verification": {
      "items": {
        "$ref": "#/components/schemas/VerificationCheck"
      },
      "title": "Verification",
      "type": "array"
    },
    "verification_detail": {
      "$ref": "#/components/schemas/VerificationDetail"
    }
  },
  "required": [
    "application_id",
    "score_id",
    "score",
    "score_percent",
    "score_lower_bound",
    "score_upper_bound",
    "data_completeness",
    "mandatory_results",
    "categories",
    "eligibility",
    "review_signals",
    "evidence",
    "analysis_summary",
    "verification",
    "scoring_version",
    "algorithm_version",
    "config_snapshot",
    "candidate",
    "resume",
    "application",
    "verification_detail",
    "score_detail",
    "evidence_groups",
    "explanation"
  ],
  "title": "AnalysisData",
  "type": "object"
}
```

### `ApiResponse_ComparisonData_`

```json
{
  "properties": {
    "data": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/ComparisonData"
        },
        {
          "type": "null"
        }
      ]
    },
    "errors": {
      "anyOf": [
        {},
        {
          "type": "null"
        }
      ],
      "title": "Errors"
    },
    "message": {
      "title": "Message",
      "type": "string"
    },
    "success": {
      "title": "Success",
      "type": "boolean"
    }
  },
  "required": [
    "success",
    "message"
  ],
  "title": "ApiResponse[ComparisonData]",
  "type": "object"
}
```

### `ApiResponse_RankData_`

```json
{
  "properties": {
    "data": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/RankData"
        },
        {
          "type": "null"
        }
      ]
    },
    "errors": {
      "anyOf": [
        {},
        {
          "type": "null"
        }
      ],
      "title": "Errors"
    },
    "message": {
      "title": "Message",
      "type": "string"
    },
    "success": {
      "title": "Success",
      "type": "boolean"
    }
  },
  "required": [
    "success",
    "message"
  ],
  "title": "ApiResponse[RankData]",
  "type": "object"
}
```

### `ApiResponse_RankingHistoryPage_`

```json
{
  "properties": {
    "data": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/RankingHistoryPage"
        },
        {
          "type": "null"
        }
      ]
    },
    "errors": {
      "anyOf": [
        {},
        {
          "type": "null"
        }
      ],
      "title": "Errors"
    },
    "message": {
      "title": "Message",
      "type": "string"
    },
    "success": {
      "title": "Success",
      "type": "boolean"
    }
  },
  "required": [
    "success",
    "message"
  ],
  "title": "ApiResponse[RankingHistoryPage]",
  "type": "object"
}
```

### `ApiResponse_RankingPage_`

```json
{
  "properties": {
    "data": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/RankingPage"
        },
        {
          "type": "null"
        }
      ]
    },
    "errors": {
      "anyOf": [
        {},
        {
          "type": "null"
        }
      ],
      "title": "Errors"
    },
    "message": {
      "title": "Message",
      "type": "string"
    },
    "success": {
      "title": "Success",
      "type": "boolean"
    }
  },
  "required": [
    "success",
    "message"
  ],
  "title": "ApiResponse[RankingPage]",
  "type": "object"
}
```

### `ApiResponse_VerifyData_`

```json
{
  "properties": {
    "data": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/VerifyData"
        },
        {
          "type": "null"
        }
      ]
    },
    "errors": {
      "anyOf": [
        {},
        {
          "type": "null"
        }
      ],
      "title": "Errors"
    },
    "message": {
      "title": "Message",
      "type": "string"
    },
    "success": {
      "title": "Success",
      "type": "boolean"
    }
  },
  "required": [
    "success",
    "message"
  ],
  "title": "ApiResponse[VerifyData]",
  "type": "object"
}
```

### `ApplicationDetail`

```json
{
  "properties": {
    "id": {
      "format": "uuid",
      "title": "Id",
      "type": "string"
    },
    "job_id": {
      "format": "uuid",
      "title": "Job Id",
      "type": "string"
    },
    "job_title": {
      "title": "Job Title",
      "type": "string"
    },
    "status": {
      "title": "Status",
      "type": "string"
    },
    "status_history": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "title": "Status History",
      "type": "array"
    }
  },
  "required": [
    "id",
    "job_id",
    "job_title",
    "status",
    "status_history"
  ],
  "title": "ApplicationDetail",
  "type": "object"
}
```

### `ApplicationStatusPage`

```json
{
  "properties": {
    "items": {
      "items": {
        "$ref": "#/components/schemas/StatusHistoryEntry"
      },
      "title": "Items",
      "type": "array"
    },
    "page": {
      "minimum": 1.0,
      "title": "Page",
      "type": "integer"
    },
    "page_size": {
      "maximum": 100.0,
      "minimum": 1.0,
      "title": "Page Size",
      "type": "integer"
    },
    "total": {
      "minimum": 0.0,
      "title": "Total",
      "type": "integer"
    },
    "total_pages": {
      "minimum": 0.0,
      "title": "Total Pages",
      "type": "integer"
    }
  },
  "required": [
    "items",
    "page",
    "page_size",
    "total",
    "total_pages"
  ],
  "title": "ApplicationStatusPage",
  "type": "object"
}
```

### `ApplicationStatusPatch`

```json
{
  "additionalProperties": false,
  "properties": {
    "reason": {
      "anyOf": [
        {
          "maxLength": 1000,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Reason"
    },
    "status": {
      "enum": [
        "applied",
        "processing",
        "analyzed",
        "shortlisted",
        "rejected",
        "withdrawn"
      ],
      "title": "Status",
      "type": "string"
    }
  },
  "required": [
    "status"
  ],
  "title": "ApplicationStatusPatch",
  "type": "object"
}
```

### `Body_upload_resumes_api_v1_jobs__job_id__resumes_post`

```json
{
  "properties": {
    "files": {
      "description": "One or more resumes: PDF, DOCX, JPEG or PNG (max 10 MB each).",
      "items": {
        "format": "binary",
        "type": "string"
      },
      "title": "Files",
      "type": "array"
    }
  },
  "required": [
    "files"
  ],
  "title": "Body_upload_resumes_api_v1_jobs__job_id__resumes_post",
  "type": "object"
}
```

### `CandidateDetail`

```json
{
  "properties": {
    "display_name": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Display Name"
    },
    "email": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Email"
    },
    "id": {
      "anyOf": [
        {
          "format": "uuid",
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Id"
    },
    "links": {
      "additionalProperties": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "null"
          }
        ]
      },
      "title": "Links",
      "type": "object"
    },
    "phone": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Phone"
    },
    "profile": {
      "additionalProperties": true,
      "title": "Profile",
      "type": "object"
    }
  },
  "required": [
    "id",
    "display_name",
    "email",
    "phone",
    "links",
    "profile"
  ],
  "title": "CandidateDetail",
  "type": "object"
}
```

### `CategoryAnalysis`

```json
{
  "properties": {
    "components": {
      "additionalProperties": true,
      "title": "Components",
      "type": "object"
    },
    "evidence_ids": {
      "items": {
        "type": "string"
      },
      "title": "Evidence Ids",
      "type": "array"
    },
    "match": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "title": "Match"
    },
    "notes": {
      "items": {
        "type": "string"
      },
      "title": "Notes",
      "type": "array"
    },
    "status": {
      "enum": [
        "known",
        "unknown",
        "not_applicable"
      ],
      "title": "Status",
      "type": "string"
    },
    "weight": {
      "title": "Weight",
      "type": "number"
    },
    "weighted_contribution": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "title": "Weighted Contribution"
    }
  },
  "required": [
    "status",
    "weight"
  ],
  "title": "CategoryAnalysis",
  "type": "object"
}
```

### `CompanyCreateRequest`

```json
{
  "properties": {
    "description": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Description"
    },
    "industry": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Industry"
    },
    "location": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Location"
    },
    "name": {
      "title": "Name",
      "type": "string"
    },
    "website": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Website"
    }
  },
  "required": [
    "name"
  ],
  "title": "CompanyCreateRequest",
  "type": "object"
}
```

### `CompanyMemberGrantRequest`

```json
{
  "properties": {
    "email": {
      "format": "email",
      "title": "Email",
      "type": "string"
    }
  },
  "required": [
    "email"
  ],
  "title": "CompanyMemberGrantRequest",
  "type": "object"
}
```

### `CompanyUpdateRequest`

```json
{
  "properties": {
    "description": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Description"
    },
    "industry": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Industry"
    },
    "location": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Location"
    },
    "name": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Name"
    },
    "website": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Website"
    }
  },
  "title": "CompanyUpdateRequest",
  "type": "object"
}
```

### `CompareRequest`

```json
{
  "additionalProperties": false,
  "properties": {
    "application_ids": {
      "items": {
        "format": "uuid",
        "type": "string"
      },
      "maxItems": 4,
      "minItems": 2,
      "title": "Application Ids",
      "type": "array"
    }
  },
  "required": [
    "application_ids"
  ],
  "title": "CompareRequest",
  "type": "object"
}
```

### `ComparisonData`

```json
{
  "properties": {
    "applications": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "title": "Applications",
      "type": "array"
    },
    "categories": {
      "additionalProperties": {
        "items": {
          "additionalProperties": true,
          "type": "object"
        },
        "type": "array"
      },
      "title": "Categories",
      "type": "object"
    },
    "differences": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "title": "Differences",
      "type": "array"
    },
    "disclaimers": {
      "items": {
        "type": "string"
      },
      "title": "Disclaimers",
      "type": "array"
    },
    "mandatory_coverage": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "title": "Mandatory Coverage",
      "type": "array"
    },
    "skill_coverage": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "title": "Skill Coverage",
      "type": "array"
    }
  },
  "required": [
    "applications",
    "categories",
    "skill_coverage",
    "mandatory_coverage",
    "differences",
    "disclaimers"
  ],
  "title": "ComparisonData",
  "type": "object"
}
```

### `ExplanationDetail`

```json
{
  "properties": {
    "ai_status": {
      "enum": [
        "available",
        "pending",
        "failed",
        "unavailable"
      ],
      "title": "Ai Status",
      "type": "string"
    },
    "ai_summary": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "type": "null"
        }
      ],
      "title": "Ai Summary"
    },
    "deterministic_summary": {
      "items": {
        "type": "string"
      },
      "title": "Deterministic Summary",
      "type": "array"
    },
    "disclaimer": {
      "title": "Disclaimer",
      "type": "string"
    }
  },
  "required": [
    "deterministic_summary",
    "ai_summary",
    "ai_status",
    "disclaimer"
  ],
  "title": "ExplanationDetail",
  "type": "object"
}
```

### `GoogleOAuthRequest`

```json
{
  "properties": {
    "id_token": {
      "title": "Id Token",
      "type": "string"
    }
  },
  "required": [
    "id_token"
  ],
  "title": "GoogleOAuthRequest",
  "type": "object"
}
```

### `HTTPValidationError`

```json
{
  "properties": {
    "detail": {
      "items": {
        "$ref": "#/components/schemas/ValidationError"
      },
      "title": "Detail",
      "type": "array"
    }
  },
  "title": "HTTPValidationError",
  "type": "object"
}
```

### `JobAccessGrantRequest`

```json
{
  "properties": {
    "access_level": {
      "$ref": "#/components/schemas/JobAccessLevel",
      "default": "viewer"
    },
    "email": {
      "format": "email",
      "title": "Email",
      "type": "string"
    }
  },
  "required": [
    "email"
  ],
  "title": "JobAccessGrantRequest",
  "type": "object"
}
```

### `JobAccessLevel`

```json
{
  "enum": [
    "viewer",
    "editor"
  ],
  "title": "JobAccessLevel",
  "type": "string"
}
```

### `JobCreateRequest`

```json
{
  "properties": {
    "department": {
      "anyOf": [
        {
          "maxLength": 255,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Department"
    },
    "description": {
      "minLength": 1,
      "title": "Description",
      "type": "string"
    },
    "employment_type": {
      "$ref": "#/components/schemas/EmploymentType"
    },
    "location": {
      "anyOf": [
        {
          "maxLength": 255,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Location"
    },
    "openings": {
      "default": 1,
      "minimum": 1.0,
      "title": "Openings",
      "type": "integer"
    },
    "title": {
      "maxLength": 255,
      "minLength": 1,
      "title": "Title",
      "type": "string"
    },
    "work_mode": {
      "$ref": "#/components/schemas/WorkMode"
    }
  },
  "required": [
    "title",
    "description",
    "employment_type",
    "work_mode"
  ],
  "title": "JobCreateRequest",
  "type": "object"
}
```

### `EmploymentType`

```json
{
  "enum": [
    "full_time",
    "part_time",
    "contract",
    "temporary",
    "intern"
  ],
  "title": "EmploymentType",
  "type": "string"
}
```

### `JobRequirementCreateRequest`

```json
{
  "properties": {
    "category": {
      "$ref": "#/components/schemas/RequirementCategory"
    },
    "importance": {
      "$ref": "#/components/schemas/RequirementImportance"
    },
    "is_mandatory": {
      "title": "Is Mandatory",
      "type": "boolean"
    },
    "name": {
      "maxLength": 255,
      "minLength": 1,
      "title": "Name",
      "type": "string"
    },
    "requirement_type": {
      "$ref": "#/components/schemas/RequirementType"
    },
    "weight": {
      "default": 0.0,
      "maximum": 1.0,
      "minimum": 0.0,
      "title": "Weight",
      "type": "number"
    }
  },
  "required": [
    "category",
    "name",
    "requirement_type",
    "importance",
    "is_mandatory"
  ],
  "title": "JobRequirementCreateRequest",
  "type": "object"
}
```

### `JobRequirementUpdateRequest`

```json
{
  "properties": {
    "category": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/RequirementCategory"
        },
        {
          "type": "null"
        }
      ]
    },
    "importance": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/RequirementImportance"
        },
        {
          "type": "null"
        }
      ]
    },
    "is_mandatory": {
      "anyOf": [
        {
          "type": "boolean"
        },
        {
          "type": "null"
        }
      ],
      "title": "Is Mandatory"
    },
    "name": {
      "anyOf": [
        {
          "maxLength": 255,
          "minLength": 1,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Name"
    },
    "requirement_type": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/RequirementType"
        },
        {
          "type": "null"
        }
      ]
    },
    "weight": {
      "anyOf": [
        {
          "maximum": 1.0,
          "minimum": 0.0,
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "title": "Weight"
    }
  },
  "title": "JobRequirementUpdateRequest",
  "type": "object"
}
```

### `JobUpdateRequest`

```json
{
  "properties": {
    "department": {
      "anyOf": [
        {
          "maxLength": 255,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Department"
    },
    "description": {
      "anyOf": [
        {
          "minLength": 1,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Description"
    },
    "employment_type": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/EmploymentType"
        },
        {
          "type": "null"
        }
      ]
    },
    "location": {
      "anyOf": [
        {
          "maxLength": 255,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Location"
    },
    "openings": {
      "anyOf": [
        {
          "minimum": 1.0,
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "title": "Openings"
    },
    "title": {
      "anyOf": [
        {
          "maxLength": 255,
          "minLength": 1,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Title"
    },
    "work_mode": {
      "anyOf": [
        {
          "$ref": "#/components/schemas/WorkMode"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "title": "JobUpdateRequest",
  "type": "object"
}
```

### `LogoutRequest`

```json
{
  "properties": {
    "refresh_token": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Refresh Token"
    }
  },
  "title": "LogoutRequest",
  "type": "object"
}
```

### `RankData`

```json
{
  "properties": {
    "algorithm_version": {
      "title": "Algorithm Version",
      "type": "string"
    },
    "config_hash": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Config Hash"
    },
    "count": {
      "title": "Count",
      "type": "integer"
    },
    "items": {
      "items": {
        "$ref": "#/components/schemas/RankedItem"
      },
      "title": "Items",
      "type": "array"
    },
    "limit": {
      "title": "Limit",
      "type": "integer"
    },
    "offset": {
      "title": "Offset",
      "type": "integer"
    },
    "provider_snapshot": {
      "additionalProperties": true,
      "title": "Provider Snapshot",
      "type": "object"
    },
    "run_id": {
      "format": "uuid",
      "title": "Run Id",
      "type": "string"
    },
    "scoring_version": {
      "title": "Scoring Version",
      "type": "string"
    },
    "total_count": {
      "title": "Total Count",
      "type": "integer"
    }
  },
  "required": [
    "run_id",
    "count",
    "total_count",
    "offset",
    "limit",
    "scoring_version",
    "algorithm_version",
    "items"
  ],
  "title": "RankData",
  "type": "object"
}
```

### `RankRequest`

```json
{
  "additionalProperties": false,
  "properties": {
    "application_ids": {
      "anyOf": [
        {
          "items": {
            "format": "uuid",
            "type": "string"
          },
          "type": "array"
        },
        {
          "type": "null"
        }
      ],
      "title": "Application Ids"
    },
    "eligibility": {
      "anyOf": [
        {
          "enum": [
            "eligible",
            "needs_review",
            "potentially_ineligible"
          ],
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Eligibility"
    },
    "force_rescore": {
      "default": false,
      "title": "Force Rescore",
      "type": "boolean"
    },
    "limit": {
      "default": 50,
      "maximum": 200.0,
      "minimum": 1.0,
      "title": "Limit",
      "type": "integer"
    },
    "max_score": {
      "anyOf": [
        {
          "maximum": 100.0,
          "minimum": 0.0,
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "title": "Max Score"
    },
    "min_score": {
      "anyOf": [
        {
          "maximum": 100.0,
          "minimum": 0.0,
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "title": "Min Score"
    },
    "offset": {
      "default": 0,
      "minimum": 0.0,
      "title": "Offset",
      "type": "integer"
    },
    "scoring_version": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Scoring Version"
    },
    "status": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Status"
    },
    "verification_status": {
      "anyOf": [
        {
          "enum": [
            "passed",
            "needs_review",
            "not_verified",
            "failed"
          ],
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Verification Status"
    }
  },
  "title": "RankRequest",
  "type": "object"
}
```

### `RankedItem`

```json
{
  "properties": {
    "application_created_at": {
      "title": "Application Created At",
      "type": "string"
    },
    "application_id": {
      "format": "uuid",
      "title": "Application Id",
      "type": "string"
    },
    "data_completeness": {
      "title": "Data Completeness",
      "type": "number"
    },
    "eligibility": {
      "enum": [
        "eligible",
        "needs_review",
        "potentially_ineligible"
      ],
      "title": "Eligibility",
      "type": "string"
    },
    "rank": {
      "title": "Rank",
      "type": "integer"
    },
    "score": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "title": "Score"
    },
    "skills_score": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "title": "Skills Score"
    },
    "status": {
      "title": "Status",
      "type": "string"
    },
    "verification_statuses": {
      "items": {
        "type": "string"
      },
      "title": "Verification Statuses",
      "type": "array"
    }
  },
  "required": [
    "application_id",
    "application_created_at",
    "score",
    "eligibility",
    "data_completeness",
    "status",
    "rank"
  ],
  "title": "RankedItem",
  "type": "object"
}
```

### `RankingHistoryPage`

```json
{
  "properties": {
    "items": {
      "items": {
        "$ref": "#/components/schemas/RankingRunSummary"
      },
      "title": "Items",
      "type": "array"
    },
    "limit": {
      "title": "Limit",
      "type": "integer"
    },
    "offset": {
      "title": "Offset",
      "type": "integer"
    }
  },
  "required": [
    "items",
    "offset",
    "limit"
  ],
  "title": "RankingHistoryPage",
  "type": "object"
}
```

### `RankingPage`

```json
{
  "properties": {
    "algorithm_version": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Algorithm Version"
    },
    "filters_applied": {
      "additionalProperties": true,
      "title": "Filters Applied",
      "type": "object"
    },
    "items": {
      "items": {
        "$ref": "#/components/schemas/RankedItem"
      },
      "title": "Items",
      "type": "array"
    },
    "limit": {
      "title": "Limit",
      "type": "integer"
    },
    "offset": {
      "title": "Offset",
      "type": "integer"
    },
    "run_id": {
      "anyOf": [
        {
          "format": "uuid",
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Run Id"
    },
    "scoring_version": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Scoring Version"
    },
    "total_count": {
      "title": "Total Count",
      "type": "integer"
    }
  },
  "required": [
    "run_id",
    "total_count",
    "offset",
    "limit",
    "items"
  ],
  "title": "RankingPage",
  "type": "object"
}
```

### `RankingRunSummary`

```json
{
  "properties": {
    "algorithm_version": {
      "title": "Algorithm Version",
      "type": "string"
    },
    "config_hash": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Config Hash"
    },
    "count": {
      "title": "Count",
      "type": "integer"
    },
    "created_at": {
      "title": "Created At",
      "type": "string"
    },
    "filters_applied": {
      "additionalProperties": true,
      "title": "Filters Applied",
      "type": "object"
    },
    "job_id": {
      "format": "uuid",
      "title": "Job Id",
      "type": "string"
    },
    "job_requirements_hash": {
      "title": "Job Requirements Hash",
      "type": "string"
    },
    "provider_snapshot": {
      "additionalProperties": true,
      "title": "Provider Snapshot",
      "type": "object"
    },
    "run_id": {
      "format": "uuid",
      "title": "Run Id",
      "type": "string"
    },
    "scoring_version": {
      "title": "Scoring Version",
      "type": "string"
    },
    "triggered_by": {
      "anyOf": [
        {
          "format": "uuid",
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Triggered By"
    }
  },
  "required": [
    "run_id",
    "job_id",
    "job_requirements_hash",
    "filters_applied",
    "scoring_version",
    "algorithm_version",
    "triggered_by",
    "created_at",
    "count"
  ],
  "title": "RankingRunSummary",
  "type": "object"
}
```

### `RefreshTokenRequest`

```json
{
  "properties": {
    "refresh_token": {
      "title": "Refresh Token",
      "type": "string"
    }
  },
  "required": [
    "refresh_token"
  ],
  "title": "RefreshTokenRequest",
  "type": "object"
}
```

### `RequirementCategory`

```json
{
  "enum": [
    "skills",
    "experience",
    "education",
    "certification",
    "language",
    "responsibility",
    "other"
  ],
  "title": "RequirementCategory",
  "type": "string"
}
```

### `RequirementExtractionRequest`

```json
{
  "properties": {
    "description": {
      "anyOf": [
        {
          "minLength": 1,
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Description"
    }
  },
  "title": "RequirementExtractionRequest",
  "type": "object"
}
```

### `RequirementImportance`

```json
{
  "enum": [
    "low",
    "medium",
    "high"
  ],
  "title": "RequirementImportance",
  "type": "string"
}
```

### `RequirementType`

```json
{
  "enum": [
    "mandatory",
    "preferred"
  ],
  "title": "RequirementType",
  "type": "string"
}
```

### `ResumeDetail`

```json
{
  "properties": {
    "content_hash_prefix": {
      "title": "Content Hash Prefix",
      "type": "string"
    },
    "content_type": {
      "title": "Content Type",
      "type": "string"
    },
    "extraction_version": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "title": "Extraction Version"
    },
    "file_name": {
      "title": "File Name",
      "type": "string"
    },
    "page_count": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "title": "Page Count"
    },
    "parse_status": {
      "title": "Parse Status",
      "type": "string"
    },
    "parser_version": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Parser Version"
    },
    "size_bytes": {
      "title": "Size Bytes",
      "type": "integer"
    },
    "uploaded_at": {
      "title": "Uploaded At",
      "type": "string"
    }
  },
  "required": [
    "file_name",
    "content_type",
    "size_bytes",
    "page_count",
    "uploaded_at",
    "parse_status",
    "parser_version",
    "extraction_version",
    "content_hash_prefix"
  ],
  "title": "ResumeDetail",
  "type": "object"
}
```

### `ScoreDetail`

```json
{
  "properties": {
    "categories": {
      "additionalProperties": {
        "$ref": "#/components/schemas/CategoryAnalysis"
      },
      "title": "Categories",
      "type": "object"
    },
    "data_completeness": {
      "title": "Data Completeness",
      "type": "number"
    },
    "eligibility": {
      "enum": [
        "eligible",
        "needs_review",
        "potentially_ineligible"
      ],
      "title": "Eligibility",
      "type": "string"
    },
    "lower_bound": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "title": "Lower Bound"
    },
    "mandatory_results": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "title": "Mandatory Results",
      "type": "array"
    },
    "rank": {
      "anyOf": [
        {
          "type": "integer"
        },
        {
          "type": "null"
        }
      ],
      "title": "Rank"
    },
    "ranking_run_id": {
      "anyOf": [
        {
          "format": "uuid",
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Ranking Run Id"
    },
    "review_signals": {
      "items": {
        "type": "string"
      },
      "title": "Review Signals",
      "type": "array"
    },
    "total": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "title": "Total"
    },
    "upper_bound": {
      "anyOf": [
        {
          "type": "number"
        },
        {
          "type": "null"
        }
      ],
      "title": "Upper Bound"
    }
  },
  "required": [
    "total",
    "lower_bound",
    "upper_bound",
    "data_completeness",
    "eligibility",
    "mandatory_results",
    "review_signals",
    "categories",
    "rank",
    "ranking_run_id"
  ],
  "title": "ScoreDetail",
  "type": "object"
}
```

### `StatusHistoryEntry`

```json
{
  "properties": {
    "actor_type": {
      "enum": [
        "user",
        "system"
      ],
      "title": "Actor Type",
      "type": "string"
    },
    "actor_user_id": {
      "anyOf": [
        {
          "format": "uuid",
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Actor User Id"
    },
    "application_id": {
      "format": "uuid",
      "title": "Application Id",
      "type": "string"
    },
    "company_id": {
      "format": "uuid",
      "title": "Company Id",
      "type": "string"
    },
    "created_at": {
      "format": "date-time",
      "title": "Created At",
      "type": "string"
    },
    "from_status": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "From Status"
    },
    "id": {
      "format": "uuid",
      "title": "Id",
      "type": "string"
    },
    "job_id": {
      "format": "uuid",
      "title": "Job Id",
      "type": "string"
    },
    "reason": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Reason"
    },
    "request_id": {
      "anyOf": [
        {
          "format": "uuid",
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Request Id"
    },
    "to_status": {
      "title": "To Status",
      "type": "string"
    }
  },
  "required": [
    "id",
    "application_id",
    "job_id",
    "company_id",
    "from_status",
    "to_status",
    "actor_type",
    "actor_user_id",
    "reason",
    "request_id",
    "created_at"
  ],
  "title": "StatusHistoryEntry",
  "type": "object"
}
```

### `UserLoginRequest`

```json
{
  "properties": {
    "email": {
      "format": "email",
      "title": "Email",
      "type": "string"
    },
    "password": {
      "title": "Password",
      "type": "string"
    }
  },
  "required": [
    "email",
    "password"
  ],
  "title": "UserLoginRequest",
  "type": "object"
}
```

### `UserRegisterRequest`

```json
{
  "properties": {
    "email": {
      "format": "email",
      "title": "Email",
      "type": "string"
    },
    "name": {
      "title": "Name",
      "type": "string"
    },
    "password": {
      "title": "Password",
      "type": "string"
    }
  },
  "required": [
    "name",
    "email",
    "password"
  ],
  "title": "UserRegisterRequest",
  "type": "object"
}
```

### `ValidationError`

```json
{
  "properties": {
    "ctx": {
      "title": "Context",
      "type": "object"
    },
    "input": {
      "title": "Input"
    },
    "loc": {
      "items": {
        "anyOf": [
          {
            "type": "string"
          },
          {
            "type": "integer"
          }
        ]
      },
      "title": "Location",
      "type": "array"
    },
    "msg": {
      "title": "Message",
      "type": "string"
    },
    "type": {
      "title": "Error Type",
      "type": "string"
    }
  },
  "required": [
    "loc",
    "msg",
    "type"
  ],
  "title": "ValidationError",
  "type": "object"
}
```

### `VerificationCheck`

```json
{
  "properties": {
    "check_type": {
      "title": "Check Type",
      "type": "string"
    },
    "details": {
      "additionalProperties": true,
      "title": "Details",
      "type": "object"
    },
    "signal": {
      "title": "Signal",
      "type": "string"
    },
    "status": {
      "enum": [
        "passed",
        "needs_review",
        "not_verified",
        "failed"
      ],
      "title": "Status",
      "type": "string"
    }
  },
  "required": [
    "check_type",
    "status",
    "signal"
  ],
  "title": "VerificationCheck",
  "type": "object"
}
```

### `VerificationDetail`

```json
{
  "properties": {
    "checks": {
      "items": {
        "$ref": "#/components/schemas/VerificationCheck"
      },
      "title": "Checks",
      "type": "array"
    },
    "overall_status": {
      "enum": [
        "passed",
        "needs_review",
        "not_verified",
        "failed"
      ],
      "title": "Overall Status",
      "type": "string"
    }
  },
  "required": [
    "overall_status",
    "checks"
  ],
  "title": "VerificationDetail",
  "type": "object"
}
```

### `VerifyData`

```json
{
  "properties": {
    "checks": {
      "items": {
        "$ref": "#/components/schemas/VerificationCheck"
      },
      "title": "Checks",
      "type": "array"
    },
    "disclaimer": {
      "title": "Disclaimer",
      "type": "string"
    },
    "overall_status": {
      "enum": [
        "passed",
        "needs_review",
        "not_verified",
        "failed"
      ],
      "title": "Overall Status",
      "type": "string"
    }
  },
  "required": [
    "overall_status",
    "checks",
    "disclaimer"
  ],
  "title": "VerifyData",
  "type": "object"
}
```

### `WorkMode`

```json
{
  "enum": [
    "onsite",
    "hybrid",
    "remote"
  ],
  "title": "WorkMode",
  "type": "string"
}
```
