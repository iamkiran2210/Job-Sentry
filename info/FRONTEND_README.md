# Job Sentry Web

SvelteKit + TypeScript + Tailwind v4 frontend for the Job Sentry FastAPI backend.

## 1. Run it

```bash
cp .env.example .env        # then edit PUBLIC_API_BASE_URL (read at build time: restart `dev` / rebuild after changing)
bun install                 # or: npm install
bun run dev                 # http://localhost:5173
```

Backend must be running (default `http://localhost:8000`) and allow this origin:
`ALLOWED_CORS_ORIGINS=http://localhost:5173` in the backend `.env`
(already in the backend's default list).

## 2. Connecting to the backend

The base URL lives in exactly one place: `PUBLIC_API_BASE_URL` in `.env`,
read by `src/lib/config.ts`. Every request goes through `src/lib/services/api-client.ts`, which:

- prefixes `/api/v1`
- attaches `Authorization: Bearer <access_token>`
- unwraps the backend envelope `{ success, message, data, errors }`
- on `401`, rotates the refresh token once and retries
- throws a typed `ApiError` (status, message, errors)

To change environments (staging/prod), only change `PUBLIC_API_BASE_URL`.

## 3. Adding an endpoint

1. Add a typed function in `src/lib/services/<domain>.ts` using `api<T>('/path', { method, body })`.
2. Call it from a page. Never call `fetch` inside components.
3. Take types from `openapi.json`. Don't invent fields.

```ts
export const listJobs = () => api<Job[]>('/jobs');
```

## 4. Auth

- Access token: kept in memory. Refresh token: `sessionStorage` (cleared on tab close).
- Route guard in `src/routes/(app)/+layout.ts` is UX only; the backend enforces permissions and tenant isolation.
- **Assumption to verify:** login returns `data.access_token` and `data.refresh_token`.
  The OpenAPI schema leaves this response untyped. If your backend differs, edit `src/lib/services/auth.ts` only.
- For stronger security, move the refresh token to an HttpOnly cookie on the backend.

## 4b. Google sign-in

Uses the **public** route `POST /api/v1/auth/sign/google` with `{ "id_token": "..." }`.
Do not use `/auth/google`: per the API docs it requires a Bearer token and answers
"Authentication credentials were not provided" when called before login.

1. Create a Google OAuth *Web* client. Add `http://localhost:5173` under Authorized JavaScript origins.
2. Set the same client ID in the frontend `.env` (`PUBLIC_GOOGLE_CLIENT_ID`) and backend (`GOOGLE_CLIENT_ID`). Restart
   both.
3. Empty `PUBLIC_GOOGLE_CLIENT_ID` hides the button.

## 5. Production

`bun run build` produces a static SPA in `build/` (adapter-static, `index.html` fallback).
Set `PUBLIC_API_BASE_URL` at build time.

## 5a. Candidate profile

`CandidateProfile.svelte` (used on `/candidates/[id]` and inside the application analysis page) shows a recruiter-first
profile: header with contact links and counts, tabs for Overview, Experience (timeline), Skills (grouped, searchable
chips), Projects (cards), Education, Certifications, **AI data** (confidence, method, model, warnings, identity review,
resume evidence) and **Raw data** (original extraction, unchanged). `src/lib/profile.ts` maps whatever shape the backend
returns into this view (values may be plain or `{ value, confidence, evidence }`); missing fields read "Not provided".
Evidence stays attached to items and is only shown under AI data. Nothing is claimed as verified: the header says "
Resume-derived".

## 5c. Requirements and weights

Create job and the job page share `RequirementsPanel.svelte`: manual add, AI generation (editable suggestions, nothing
saved until you add them), inline edit, and a Preferred weights editor. Weights are percentages that must total exactly
100% (checked in basis points, so 0.1 + 0.2 + 0.7 is fine). Save weights, Create job and Publish are blocked until they
do. Mandatory requirements carry no weight. On the create page the AI needs a saved job to read, so the first AI request
saves a draft; "Create job" then updates that draft and adds the requirements.

## 5b. Errors, toasts and charts

- **Errors:** every failed action shows a toast with plain-language text (network, 401 session, 403 permission, 404,
  409, 413, 422 field errors, 429, 5xx) plus the backend reference id when present. See `src/lib/errors.ts`. An expired
  session redirects to `/login`.
- **Confirmations:** deleting a draft and rejecting an application use an accessible confirm dialog.
- **Loading:** skeleton placeholders on lists and dashboards; page fade respects `prefers-reduced-motion`.
- **Charts:** [LayerChart](https://layerchart.com) (`layerchart` v2). Theme tokens live in `src/app.css`;
  `AutoViz.svelte` detects documented shapes (`funnel`, `score_distribution`, `verification`, `top_matched`, rows with a
  label and a count) and every chart has a "View values" text alternative.
- **Scores update only when ranking runs.** The ranking page warns when applicants are unscored, and the upload page can
  run ranking automatically after processing finishes.

## 6. Screens

| Route                                                 | What it does                                                                     | Backend                                                |
|-------------------------------------------------------|----------------------------------------------------------------------------------|--------------------------------------------------------|
| `/login`, `/register`                                 | Email/password auth                                                              | `/auth/login`, `/auth/register`                        |
| `/dashboard`                                          | Numeric metrics only                                                             | `/analytics/overview`                                  |
| `/jobs`, `/jobs/new`, `/jobs/[id]`, `/jobs/[id]/edit` | Jobs, lifecycle, requirements, AI suggestion review                              | `/jobs…`                                               |
| `/jobs/[id]/upload`                                   | Multi-file upload with real progress, status polling, retry                      | `/jobs/{id}/resumes`, `/resumes/{id}/status`, `/retry` |
| `/jobs/[id]/applicants`                               | Job-specific ranking, filters, pagination, select 2–4                            | `/ranking`, `/rank`, `/applicants`                     |
| `/jobs/[id]/applicants/[appId]`                       | Score breakdown, mandatory results, evidence, verification, manual status change | `/analysis`, `/verify`, `/status`                      |
| `/jobs/[id]/compare?ids=a,b`                          | Compare 2–4 applications                                                         | `/compare`                                             |
| `/candidates`                                         | Directory built from each job's applicants (no list endpoint exists), no score   | `/jobs`, `/applicants`                                 |
| `/analytics`                                          | Overview, jobs, candidates, skills, pipeline with date range                     | `/analytics/*`                                         |
| `/company`                                            | Create/edit company, team (admin-only actions enforced by backend)               | `/companies…`                                          |
| `/candidates/[id]`                                    | Candidate profile (extracted, unverified), no score                              | `/candidates/{id}`                                     |
| `/settings`                                           | Account info, my access, API health                                              | `/auth/me`, `/users/me/access`, `/health`, `/ready`    |

## 7. Known assumptions

- Many response bodies are untyped in `openapi.json` (login, jobs, applicants, analytics, mandatory results, evidence,
  compare). Those are rendered with a generic `DataView` so nothing is invented. Tighten the types once you confirm real
  payloads.
- Scores `<= 1` are formatted as fractions of 100 (display only). Confirm the backend scale.
- Application statuses are the backend's: applied, processing, analyzed, shortlisted, rejected, withdrawn. There is no
  interview, on-hold or hired status.
- Rejection is only ever a manual action with a confirmation. No score triggers it.
- Token refresh assumes `access_token` / `refresh_token` field names (login uses a tolerant extractor).

## 8. Score scale

Set `PUBLIC_SCORE_SCALE` in `.env`: `100` (scores are 0-100, default) or `1` (scores are 0-1). It controls how scores
are displayed and how the ranking min/max score filters are sent as `min_score` / `max_score`.

## 9. Tests

`npm test` runs `tests/workflow.test.ts` against a mock backend (`tests/mock-server.ts`) that follows the API reference
PDF. It walks the whole recruiter workflow through the real service layer: login, company, job and requirements, AI
suggestions (not auto-saved), publish, upload with progress and polling, ranking before and after, analysis,
verification, status change, compare, directory, all analytics tabs, token refresh and the Google fallback. It checks
the app against the documented shapes, not against your real backend.

## 10. Checks

`npm run check` (0 errors), `npm test` (28 passing) and `npm run build` pass.
