# Candidate Intelligence Engine (Phase 4)

Candidate Intelligence adds explainable, versioned decision-support signals to one authorized job's applications. It
does not compare candidates across jobs, infer identity, prove employment or skill, or reject applicants.

## Architecture and data flow

`api/` defines the five HTTP routes and Pydantic v2 contracts. `service.py` authorizes through `JobsService`, builds a
frozen allowlist `ScoringInputs`, collects and persists evidence, and reads score/ranking snapshots. `evidence/`
provides exact/alias matching, embedding and LLM adapters behind protocols. `scoring/category_formulas.py` contains
deterministic Decimal formulas. `verification/` contains pure checks plus an HTTP reachability checker with injected
transport and DNS resolver. `ranking/` owns stable filter/sort/page behavior.

The scoring DTO includes only job requirement text/category/mandatory status and extracted skills, work history,
projects, education and certifications. It excludes names, gender, age, date of birth, photos, nationality, ethnicity,
religion, marital status, address, contact details and other identity/proxy fields. Provider output is evidence; the
deterministic scorers and aggregate calculate the final score.

## Scoring formulas

Default category weights are skills 0.40, experience 0.25, projects 0.20, education 0.10 and certifications 0.05. All
five weights must be non-negative and sum to 1.0.

| Category       | Formula and evidence behavior                                                                                                                                                                                                                                                                                                                                                                            |
|----------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Skills         | Exact match credit is 1.0; configured alias credit is 1.0 and is labeled separately; semantic credit is capped at 0.60 using `cap × clamp((cosine − 0.55) / (0.85 − 0.55), 0, 1)`. Mandatory skill requirements have twice the weight of preferred requirements. A missing match is zero only when evidence established a miss; absent evidence remains unknown.                                         |
| Experience     | Relevant date intervals are merged before counting months. Open roles end at the injected `as_of` date. If required years exist, `years_fit = min(relevant_years / required_years, 1)` and the result is the equal-weight mean of `years_fit` and mean relevance. If only relevance is available, relevance is used with `partial_experience_evidence`; without required years, relevance alone is used. |
| Projects       | Mean relevance of up to the top three projects. Sort by relevance descending, then project ID ascending. Fewer than three known projects carry `fewer_than_n_projects`; no known relevance is unknown.                                                                                                                                                                                                   |
| Education      | Compare recognized ordinal levels: a level at or above the requirement scores 1.0, one level below scores 0.5, and two or more below scores 0.0. Missing/unrecognized degrees are unknown; no education requirement is `not_applicable`. `field_mismatch` is a separate signal and does not change the ordinal score.                                                                                    |
| Certifications | Weighted fraction of listed requirements matched through normalized names/aliases. No requirements is `not_applicable`; requirements without a held-certification list are unknown; a known list with no match scores 0. Expired certifications do not match and carry `cert_expired`; unknown expiry can match but carries `cert_expiry_unknown`.                                                       |

Category match values are clamped to [0, 1] and rounded to 4 decimal places at output. Totals and bounds are percentages
rounded to 2 places. Completeness is rounded to 3 places. All calculations use `Decimal` and `ROUND_HALF_UP` at the
output edge.

Unknown categories are omitted from the known-score denominator and reduce completeness. `not_applicable` categories are
omitted from both the numerator and denominator. The total is `100 × sum(known weight × match) / sum(known weight)`. The
lower bound uses applicable weight as denominator; the upper bound treats unknown applicable categories as 1.0. No known
category means `score: null`, lower bound 0 and upper bound 100 when categories apply.

Semantic `similarity` stores raw cosine in [-1, 1]; negative cosine receives zero semantic credit. Similarity, exact
text, public metadata and LLM output are not proof of skill or employment. Mandatory requirements are evaluated
separately. Only exact, alias or explicit rule evidence can mark one `met`; `not_met` produces `potentially_ineligible`,
and unknown produces `needs_review`. Mandatory evaluation does not zero a score, hide an applicant or change application
status.

## Verification behavior

`passed` means a check ran and found no defined issue; `needs_review` records ambiguity or an advisory signal;
`not_verified` means data is absent, disabled or unavailable; `failed` means present input was demonstrably invalid or
unsafe. Overall precedence is `failed > needs_review > not_verified > passed`.

| Check            | Behavior                                                                                                                                                                                                                                                                                                                                                                                                                                            |
|------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Email            | Trims edge whitespace and normalizes case. Internal whitespace removal, multiple addresses, role accounts and known disposable domains need review. Malformed input fails. Absent/disabled checks are not verified. Syntax does not prove address control.                                                                                                                                                                                          |
| Phone            | Uses `phonenumbers`; supports international `+`, configured local region, converts `00`, returns E.164 and separates extension. Multiple or possible-but-not-valid numbers need review; impossible/unparseable values fail. A local number without a configured region is not verified.                                                                                                                                                             |
| Completeness     | Uses configured thresholds (default pass 0.80, fail floor 0.50): at/above pass is passed, between thresholds and exactly at the floor need review, below floor fails. No parsed profile is not verified.                                                                                                                                                                                                                                            |
| Timeline         | Malformed dates, end before start and future dates fail. Overlap beyond tolerance and long gaps need review with neutral wording. Fewer than two dated roles are not verified.                                                                                                                                                                                                                                                                      |
| Duplicates       | Compares normalized email, valid E.164 phone and resume hash within configured job or company scope. A match needs review; no comparison data is not verified. This check never returns failed.                                                                                                                                                                                                                                                     |
| Portfolio/GitHub | Format and optional reachability are separate. Private/reserved IPs fail with `ssrf_blocked`. Redirects are capped at three hops and each DNS/redirect target is revalidated; cross-host redirects need review. HEAD 405/501 uses one GET fallback. 403, 404 and 5xx need review; timeout/DNS/disabled/absent are not verified. GitHub accepts profile or repository paths on `github.com`; other hosts fail and malformed path shape needs review. |

The verify response masks normalized contact values and states that checks do not prove identity, employment or skill. A
reachable URL proves nothing about skills or employment. No cookies or authorization headers are sent by reachability
checks.

## Ranking, runs and history

Ranking is restricted to one authorized job. It sorts by total score descending (null last), eligibility (`eligible`,
`needs_review`, `potentially_ineligible`), skills match descending, completeness descending, application creation time
ascending, then application ID ascending. Ranks start at 1 with no gaps. Filters run before pagination, so counts and
pages refer to the filtered ordering.

`ranking_run` stores one immutable run record with counts, filters, scoring/algorithm/provider versions,
requirements/config hashes and triggering user. `ranking_history` stores per-application ranks, score IDs, tie-break
keys and the same provenance; it also stores the ordered snapshot used to reproduce pages. Database triggers reject
UPDATE and DELETE on both tables. Re-ranking creates a new `run_id` and preserves older rows. A PostgreSQL transaction
advisory lock keyed by job returns HTTP 409 when another rank operation holds it. Current scores are reused when the
inputs/configuration match; `force_rescore` writes a new score snapshot.

The core schema is in `app/modules/candidate_intelligence/models.py`; revisions are in `migrations/versions/`. Revision
`e82c4a91d307` is immutable; subsequent changes are additive revisions. `ScoreEvidenceRecord` stores typed evidence
columns, including `embedding vector(384)`, plus a JSON evidence snapshot.

## Version changes and safe migrations

Bump `INTELLIGENCE_SCORING_VERSION` when weights, formulas, mappings, thresholds, matching or missing-data semantics
change. Bump `INTELLIGENCE_ALGORITHM_VERSION` for implementation changes that preserve scoring semantics. Keep
providers, model versions and prompt version in the run provenance.

Run online migrations only against a disposable database whose name contains `test`, through the guarded wrapper:

```bash
TEST_DATABASE_URL='postgresql+asyncpg://user:***@localhost:5432/job_sentry_test' \
  scripts/alembic_test.sh upgrade head
```

`scripts/alembic_test.sh` sets `ALEMBIC_TARGET=test` and `ALEMBIC_DATABASE_URL` from `TEST_DATABASE_URL`.
`ALEMBIC_DATABASE_URL` takes precedence over the app setting. The guard rejects non-test targets in test mode and
requires `ALEMBIC_CONFIRM_DB=<database-name>` for online destructive migration commands against non-test names. Never
set that confirmation in an agent workflow. Offline `--sql` generation is allowed. The CI fixture creates a separate
`job_sentry_phase4_alembic_test`, installs `vector`, migrates through the wrapper, and drops it after use.

## API routes

All routes are under `/api/v1`; job access is checked with Phase 2 rules.

| Method and path                               | Purpose                                                                                                                                                                                                             |
|-----------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `POST /applications/{application_id}/verify`  | Runs and stores deterministic verification checks. Returns each status and the responsible-use disclaimer; contact values are masked.                                                                               |
| `GET /applications/{application_id}/analysis` | Read-only latest score, categories, evidence and verification. Before scoring it returns `score: null`, `evidence: []`, `status_note: "not_scored"`.                                                                |
| `POST /jobs/{job_id}/rank`                    | Starts a versioned run. Body accepts `scoring_version`, `application_ids`, `force_rescore`, ranking filters, `offset` and `limit`. IDs outside the job or unknown versions return 422; a held job lock returns 409. |
| `GET /jobs/{job_id}/ranking`                  | Reads the latest run or `run_id`; supports eligibility, verification status, score range, status and page/page-size filters. Unknown run IDs return 404; no run returns an empty 200.                               |
| `GET /jobs/{job_id}/ranking/history`          | Reads paginated `ranking_run` summaries, newest first and job-scoped.                                                                                                                                               |

The Pydantic request models forbid extra fields. Score filters are limited to [0, 100]; page size is limited
to [1, 100]. Missing or other-company resources return 404 to avoid an existence leak; authorized viewers cannot invoke
edit-only verify/rank operations.

## Limitations and responsible use

Extracted resumes can be incomplete or wrong. Similarity, public-profile metadata, contact syntax and timeline checks
are advisory signals only. Public profile data does not establish authorship, employment or skills. Never use protected
characteristics in requirements, prompts, scorers or downstream decisions. Do not use the score for autonomous
rejection; a human must review the underlying evidence and candidate materials.
