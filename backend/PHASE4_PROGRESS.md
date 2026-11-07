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
