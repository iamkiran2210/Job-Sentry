S1 checkpoint (incomplete)
Done: added allowlist input builder, pure helper names, category formulas and Decimal aggregate helper; existing focused tests remain green.
Tests run: `UV_CACHE_DIR=/tmp/uv-cache uv run --project backend pytest -q tests/candidate_intelligence` — 9 passed.
Open: ScoringService is only a facade over old analysis; pure category formulas are not wired into persistence; DB golden/sentinel/A–I/reproducibility tests remain.
Resume: S1. Wire one pure scorer path and read-only GETs, add smoke/sentinel/golden tests, then mark S1 done before S2.

S1 DB checkpoint
Root cause: raw aiosqlite 0.22.1 and 0.21.0 hang at connect; sqlite3 and threads work. Switched DB-backed checks to isolated pgvector `job_sentry_test`.
Fix: test fixture rejects non-test database names; no scoring production code changed during Step B.
Tests: smoke 1 passed after fixture requirement; full wiring file 1 passed, 8 failed (expected sentinel/no-shadow); original layers 9 passed; DSPy 1 passed.
Open: S1 scorer wiring and proof tests; no dependency files changed; disposable test DB is local only.

S1 checkpoint (scoring service wired; S1 remains open)
Done: ScoringService now builds a filtered ScoringInputs DTO, collects/adapts evidence, invokes the five pure category scorers, mandatory evaluator and aggregate; GET analysis is read-only and rank explicitly scores missing version records.
Tests: `UV_CACHE_DIR=/tmp/uv-cache TEST_DATABASE_URL=<isolated job_sentry_test URL> uv run --project . pytest -q tests/candidate_intelligence` — 45 passed; 36 focused wiring/fixture tests collected and run as part of the suite.
Open: DB golden fixtures currently cover A-D plus per-scorer sentinels; A-I full service fixtures and ranking provenance remain open. Verification/schema/migration work remains NOT VERIFIED.
Open items for S3: ScoreEvidence metadata columns/constraints are still missing; category_scores and as_of_date are stored in existing CandidateScore JSON fields until an additive migration is authorized.
Resume: finish S1 DB golden and stored-input reproducibility proof, then stop before S2.

## E0 hygiene and tooling (2026-11-07)
Committed migration chain (`7733755`), Alembic round-trip test and drift fixes (`040db58`), and phone possible-not-valid repair plus regression test (`fd3ca52`).
`backend/pyproject.toml` declares `pytest-timeout` in the dev group; pytest config sets a 60-second timeout and registers `integration` and `requires_pgvector`.
Added a session-scoped `alembic_db` fixture that creates `job_sentry_phase4_alembic_test`, prepares schema/vector, upgrades only through `scripts/alembic_test.sh`, yields an async engine, and drops the DB.
Validation: `pytest -q --timeout=60 backend/tests/candidate_intelligence` — 54 passed; `scripts/alembic_test.sh history` lists nine revisions, all tracked under `backend/migrations/versions`.

## Candidate intelligence implementation update (2026-11-07)

Implemented the scoring and ranking fixes plus verification/API/persistence closure work: ranking now filters before pagination and persists a full filtered order; versioned runs include provider/config provenance and immutable update protection; analysis remains read-only; endpoint data has Pydantic schemas; score/evidence metadata is explicitly stored with an additive `e82c4a91d307` migration; verification covers missing/ambiguous/malformed signals and GitHub URL format; phone numbering validation uses `phonenumbers` with an optional region setting.

Validation this update: `python -m compileall -q app/modules/candidate_intelligence migrations/versions/e82c4a91d307_candidate_intelligence_typed_evidence.py` and `git diff --check` passed. Tests and database migration round trips were not run. Open: run the candidate-intelligence suite and DB migration checks; finish ranking run locking/idempotency and DB golden A-I; investigate the DSPy stall; verify the real pgvector deployment path; run configured lint/type checks.

## E1 evidence constraint tests (2026-11-08)
Added revision `f4a1b2c3d5e6` after immutable `e82c4a91d307`; it adds evidence metadata columns and named checks while leaving `vector` untouched on downgrade.
Added Alembic-backed tests for category/signal allowlists, value and cosine ranges, proof/grounding rules, required semantic/LLM/exact metadata, source offsets, valid signal rows, and all evidence fields as columns.
Fixed semantic credit to persist zero below threshold, populated model/prompt/embedding metadata, and added pgvector list/string conversion for asyncpg.
Validation: focused evidence tests — 33 passed; Alembic migration round trip — 1 passed; full suite — 87 passed in 29.84s.

## E2 verification matrix tests (2026-11-08)
Added a table-driven verification suite covering email, phone, completeness thresholds, timelines, duplicate scope, URLs/SSRF/redirects, precedence, normalization, privacy logging, and the verify-response disclaimer.
Verification now uses E.164 normalization, configured thresholds and duplicate scope, neutral timeline gaps, explicit URL result codes, host/DNS revalidation, bounded redirects, and disabled-check `not_verified` results.
Fixed defects found by the matrix: multiple emails were missed by an anchored regex, and alphabetic-only phone input was incorrectly reported as missing region.
Validation: E2 matrix — 58 passed; full candidate-intelligence suite — 145 passed in 34.60s. HTTP requests were exercised through `httpx.MockTransport` and an injected resolver.
