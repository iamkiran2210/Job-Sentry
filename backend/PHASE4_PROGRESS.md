S1 checkpoint (incomplete)
Done: added allowlist input builder, pure helper names, category formulas and Decimal aggregate helper; existing focused tests remain green.
Tests run: `UV_CACHE_DIR=/tmp/uv-cache uv run --project backend pytest -q tests/candidate_intelligence` — 9 passed.
Open: ScoringService is only a facade over old analysis; pure category formulas are not wired into persistence; DB golden/sentinel/A–I/reproducibility tests remain.
Resume: S1. Wire one pure scorer path and read-only GETs, add smoke/sentinel/golden tests, then mark S1 done before S2.
