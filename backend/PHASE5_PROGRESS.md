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
