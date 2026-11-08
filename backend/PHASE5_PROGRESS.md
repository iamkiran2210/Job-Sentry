## F0 baseline and audit (2026-11-08)
Baseline: `tests` — 360 passed, 2 skipped in 129.25s; `tests/ai_features` — 126 passed, 2 skipped in 47.80s; Alembic has one head, `a91d6e4f2b70`.
Added Ruff and strict mypy dev declarations/configuration and created `CODEBASE_AUDIT.md`; vulture, pip-audit, detect-secrets and gitleaks are unavailable, and offline installation cannot fetch the mypy wheel, so those checks are NOT VERIFIED.
Migration files `4c8d6f1a2e73`, `7a4d91c2e6b3`, `9b1c4f6e2a71`, `a5475d55ef43`, and `f2c3a01d84b7` are modified in the worktree; left untouched and uncommitted for owner review.
F0 is complete; the audit records open cleanup tasks, including broad exception handling, an async embedding call, and the candidate-list N+1 query. No application database was used.

## F1 architecture (2026-11-08)
Added `ARCHITECTURE.md` describing the current layers, modules, dependency direction and a target tree that follows the existing feature-module layout.
The guide explicitly treats the untracked `app/ai_features` tree as an integration boundary pending ownership/track review; no source files were moved.
Validation: full suite — 360 passed, 2 skipped in 127.76s.

## F1 unused imports and dead code (2026-11-08)
Removed confirmed unused imports from `app/core/dependencies.py`, auth router/service, and candidate-intelligence models/service; relationship-registration imports were preserved.
The custom AST import scan was a screening aid only; complete dead-code detection remains NOT VERIFIED until Ruff/vulture are available offline.
Validation: full suite — 360 passed, 2 skipped in 129.54s.

## F1 timezone audit (2026-11-08)
Reviewed all `datetime.now`/`utcnow`/`fromtimestamp` calls, mapped `DateTime` columns and migrations; clocks are UTC-aware and mapped timestamps use timezone-aware columns, so no code or migration change was needed.
Corrected the audit: the resume `as_utc` helper re-exports the shared clock and is not a duplicate clock implementation.
Validation: full suite — 360 passed, 2 skipped in 135.62s.

## F1 exception handling (2026-11-08)
Google ID-token verification now masks provider exception text from 401 responses and logs only the exception type; malformed CORS JSON catches `JSONDecodeError`, and the audit distinguishes rollback-and-reraise cleanup from swallowed errors.
Regression: `tests/test_security_exception_safety.py::test_google_token_errors_do_not_expose_provider_details` — 2 parameter cases pass.
Validation: full suite — 362 passed, 2 skipped in 138.47s. An auth subset run without PostgreSQL stalled in the SQLite fixture and was interrupted; it is not counted as passing evidence.

## F1 blocking calls (2026-11-08)
Synchronous embedding provider work in asynchronous scoring now runs in Starlette's thread pool; the provider Protocol remains synchronous for simple mocks and CPU-bound implementations.
Regression: `tests/candidate_intelligence/test_nonblocking_embedding.py::test_sync_embedding_does_not_block_the_event_loop` passes after first failing against the blocking implementation.
Validation: full suite — 363 passed, 2 skipped in 133.09s.

## F3 application status workflow (2026-11-08)
Added revision `c2f6b1a8d904` after `a91d6e4f2b70`, with reversible status normalization, an append-only status history table, and the user-facing status PATCH/history endpoints. Legacy mapping: `processing` stays processing, `analyzing` maps to processing, `completed`/`analyzed` map to analyzed, existing shortlisted/rejected/withdrawn values remain, and all other values map to applied; the backup table restores exact legacy strings on downgrade.
Workers now record `applied → processing → analyzed`; terminal processing failures reset to applied. Rejection requires a reason; user/system actor rules and tenant/job authorization are enforced.
Passing coverage: `tests/candidate_intelligence/test_application_status_workflow.py` (29 cases), `tests/candidate_intelligence/test_migration_roundtrip.py::test_postgres_migration_roundtrip_and_phase1_to_3_data_survival`, and resume worker API/pipeline tests.
Validation: full suite — 391 passed, 2 skipped in 135.11s. Alembic fixture `check` reports no drift; round trip preserves schema and `vector`.

## F4 candidate analysis (2026-11-08)
Extended analysis additively with candidate/profile, sanitized resume metadata, application status history, latest verification, score/rank details, grouped evidence, and a persisted-score deterministic summary. Protected profile keys are excluded; contact details and verification contact metadata are masked unless the existing same-company access path grants PII access.
Added revision `d7f43ae83c10` for `score_explanation`; its downgrade removes only its table and indexes. Added structured explanation output validation and persistence: citations outside the current score are dropped, empty cited output becomes unavailable, generation timeout/failure is recorded, and cached output is reused by input hash/model/prompt version. The rank path queues generation only when the configured provider is Pydantic AI; GET does not invoke a generator.
Passing tests: `tests/candidate_intelligence/test_analysis_detail.py::test_analysis_returns_full_detail_and_does_not_write_or_score`; `tests/candidate_intelligence/test_explanations.py::test_explanation_drops_items_without_evidence_from_current_score`, `test_explanation_with_no_valid_evidence_is_unavailable`, and `test_generated_explanation_uses_persisted_data_and_caches`; migration fixture and round-trip tests in `test_alembic_fixture.py` and `test_migration_roundtrip.py`.
Validation: full suite — 395 passed, 2 skipped in 147.08s. Alembic round trip and drift check — 6 passed in 16.27s. The worker task path depends on the existing untracked `app/ai_features` tree; it is not independently verified outside the default mocked suite.

## F5 comparison (2026-11-08)
Added `POST /api/v1/jobs/{job_id}/compare` with a strict 2–4 unique ID request, authorized job access, same-job/company checks, current-version persisted-score requirement, and a read-only comparison assembled in request order. Comparison includes category contributions, per-skill exact/alias/semantic/none/unknown status, mandatory counts, latest verification status, deterministic evidence-backed differences, and a no-recommendation disclaimer. It does not invoke scoring or an LLM.
Passing coverage: `tests/candidate_intelligence/test_comparison.py::test_comparison_request_requires_two_to_four_unique_ids`, `test_comparison_is_job_scoped_read_only_and_reports_evidence_differences` (2, 3 and 4 application cases), and `test_compare_endpoint_preserves_requested_order_and_never_scores`.
The service tests assert deterministic repeated output, preserved order, evidence difference types, 409 for missing current scores, 422 for other-job and other-company IDs, and unchanged score-row count. The API contract is exercised for a valid two-application request.
Validation: full suite — 400 passed, 2 skipped in 151.24s. No new migration. Comparison response edge validation for every 1/5 ID API case and the exhaustive protected-attribute response audit remain NOT VERIFIED.

## F6 analytics (2026-11-08)
Added authenticated company-scoped SQL analytics routes for overview, jobs, candidates, skills, and pipeline. Date filters use UTC half-open ranges for inclusive dates; ranges over 366 days and inverted ranges return 422; cross-company job filters return 404 and mismatched company filters return 403. Aggregates run in SQL, latest scores are restricted to the current scoring version, and analytics schemas expose no demographic fields.
Passing coverage: `tests/candidate_intelligence/test_analytics.py::test_analytics_overview_and_jobs_are_sql_aggregated_and_company_scoped` asserts hand-computed KPIs, score distributions, verification distribution, skills coverage, pipeline counts, a 23:59:59Z end-boundary record, company isolation, sort allowlist, and date cap.
Validation: full suite — 401 passed, 2 skipped in 149.90s. No new migration was needed. Empty-database endpoint behavior, multi-company membership (the current user model has only one `company_id`), query-count bounds, Redis analytics caching, and EXPLAIN output on 10k rows remain NOT VERIFIED. Pipeline processing duration is derived from the existing resume start/completion timestamps; no separate `processing_run` table exists.
