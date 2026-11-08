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
