# Candidate Intelligence API

Base path: `/api/v1`. All routes require authentication and use Phase 2 job authorization. Missing and other-company
resources return 404. Viewer grants cannot run edit-only operations.

## Verify an application

`POST /applications/{application_id}/verify`

Runs the email, phone, completeness, timeline, duplicate, GitHub and portfolio checks, stores their results, and returns
a masked response.

```json
{
  "success": true,
  "message": "Verification signals recorded",
  "data": {
    "overall_status": "needs_review",
    "checks": [{
      "check_type": "phone_format",
      "status": "passed",
      "signal": "Format only; does not prove control of number",
      "details": {"normalized_e164": "********2671"}
    }],
    "disclaimer": "These checks do not prove identity, employment or skill. A reachable public URL does not prove skills or employment."
  }
}
```

Statuses are `passed`, `needs_review`, `not_verified`, and `failed`; overall precedence is failed, review, not verified,
passed. Phone/email syntax is not proof of ownership.

## Read application analysis

`GET /applications/{application_id}/analysis`

This route is read-only and never invokes scoring. Before the first scoring run, the response data includes:

```json
{"score": null, "evidence": [], "status_note": "not_scored"}
```

After scoring, the response includes score and bounds, completeness, category statuses/matches/components, mandatory
results, review signals, evidence, versions and the latest verification results.

## Create a ranking run

`POST /jobs/{job_id}/rank`

Request fields are strict (`extra="forbid"`):

```json
{
  "scoring_version": "v1.4.0",
  "application_ids": ["00000000-0000-0000-0000-000000000000"],
  "force_rescore": false,
  "offset": 0,
  "limit": 50,
  "eligibility": "eligible",
  "min_score": 50,
  "max_score": 100,
  "status": "applied",
  "verification_status": "passed"
}
```

Omit `application_ids` to include every application in the job. Unknown scoring versions or IDs outside the job return
422; invalid IDs are listed. Score filters must be within [0, 100], and `min_score` cannot exceed `max_score`. A
concurrent run for the same job returns 409. Existing scores are reused when scoring version, algorithm/configuration
and current allowlisted inputs match. `force_rescore: true` writes a separate score snapshot.

Success returns a `run_id`, item count/filtered total, offset/limit, scoring and algorithm versions, config hash,
provider snapshot, and ranked items with 1-based ranks. Each item includes eligibility, skills match, completeness and
verification statuses.

## Read a ranking page

`GET /jobs/{job_id}/ranking`

Reads the latest run; pass `run_id` to select a specific run. Supported filters are `eligibility`,
`verification_status`, `min_score`, `max_score`, and application `status`. Use `page` (1-based) and `page_size` (1–100);
legacy `offset`/`limit` are also accepted, with `limit` capped at 100. Filters run before page slicing. Unknown run IDs
return 404. With no run, returns 200 with `run_id: null` and an empty item list.

The response includes `run_id`, filtered `total_count`, offset/limit, versions, `filters_applied`, and items. Invalid
enum values, out-of-range scores/page sizes, or `min_score > max_score` return 422.

## Read ranking history

`GET /jobs/{job_id}/ranking/history`

Returns paginated `ranking_run` summaries for the requested job, newest first. Each summary includes run/job IDs,
requirements and config hashes, filters, scoring/algorithm/provider versions, triggering user, creation time and run
counts. `offset` is zero-based and `limit` is 1–200.

## Errors and responsible use

| Status | Meaning                                                                                                      |
|--------|--------------------------------------------------------------------------------------------------------------|
| 403    | The user has a viewer grant and attempted edit-only verify/rank work.                                        |
| 404    | The application/job/run is missing or outside the user's authorized company/job scope.                       |
| 409    | Another rank operation holds the job-scoped PostgreSQL advisory lock.                                        |
| 422    | Invalid request fields, enum, score/page bounds, unknown scoring version or application IDs outside the job. |

Scores and verification checks are decision-support signals. They do not prove identity, employment or skill and must
not be used for autonomous rejection.
