# F0 codebase audit

This inventory is based on source inspection and repository searches on 2026-11-08. Optional static-analysis/security tools were not installed or available in the offline wheel cache, so findings that require those tools remain unverified. No secret values are reproduced here.

| file:line | category | severity | action |
|---|---|---:|---|
| `backend/pyproject.toml:30` | tooling | medium | Add Ruff and strict mypy to the dev group; configure scoped checks. `vulture`, `pip-audit`, `detect-secrets`, and `gitleaks` are unavailable offline. |
| `backend/app/**` | unused imports / dead code | medium | A local AST scan found and removed confirmed unused imports in the shared dependency, auth, and candidate-intelligence modules. ORM imports used for relationship registration were retained. Dead-code detection remains NOT VERIFIED because vulture and Ruff are unavailable offline. |
| `backend/app/**` | circular imports | low | NOT VERIFIED: no import-graph analyzer is installed; full tests and module imports pass, which is not a cycle audit. |
| `backend/app/models/base.py:9` and `backend/app/ai_features/resumes/timeutil.py:5` | duplicate utility | low | No duplicate clock implementation: `timeutil` re-exports the shared `utc_now` helper. Keep that single implementation. |
| `backend/app/core/security.py:128` | broad exception | medium | Google token failures now return a generic unauthorized message and log only the exception type; regression test covers provider details. |
| `backend/app/core/database.py:60` | exception cleanup | low | Broad catch is required to roll back and re-raise arbitrary transaction failures; it does not swallow errors, so it remains. |
| `backend/app/core/config.py:61` | broad exception | low | JSON CORS parsing now catches only `JSONDecodeError`; malformed JSON retains the existing comma-separated fallback. |
| `backend/app/modules/jobs/router.py:276` | broad exception | medium | Replace catch-all route handling with typed domain/HTTP handling and safe error reporting. |
| `backend/app/modules/candidate_intelligence/service.py:340,429,444` | broad exception | medium | Classify embedder/LLM and optional persistence failures; add structured warning/error logs. |
| `backend/app/modules/candidate_intelligence/verification/checks.py:37,93,126` | broad exception | low | Confirm each catch is limited to malformed input normalization and narrow it where possible. |
| `backend/app/modules/candidate_intelligence/evidence/providers.py:90` | broad exception | medium | Map provider failures to typed transient/permanent outcomes and preserve cause only in redacted logs. |
| `backend/app/ai_features/resumes/parsers/pdf.py:19,51` and `docx.py:40,67` | broad exception | medium | Narrow parser exceptions and record safe failure codes; keep document contents out of logs. |
| `backend/app/ai_features/resumes/service.py:177` | broad exception | medium | Narrow cleanup/compensation failures and log the sanitized error category. |
| `backend/app/ai_features/resumes/dispatch.py:29` | swallowed exception | medium | Preserve enqueue failure state and log a structured reason without file or candidate data. |
| `backend/app/ai_features/candidates/service.py:107-146` | N+1 queries | high | The per-application loop queries resumes, profiles, and identity suggestions separately; replace with bounded eager/batched queries and add query-count tests. |
| `backend/app/modules/candidate_intelligence/service.py:115-175` | query count | medium | Analysis loads application, resume, profile, score, verification, and evidence in separate statements; add a query-count test and batch related reads where useful. |
| `backend/app/modules/candidate_intelligence/service.py:24,176-181,225` | response numeric format | medium | Scoring arithmetic is Decimal-based, but analysis/ranking response assembly converts persisted Decimals to floats; serialize fixed-scale Decimal strings at the API edge. |
| `backend/app/modules/candidate_intelligence/service.py:432,447` | blocking call in async path | high | Semantic embedding now runs via `run_in_threadpool`; `tests/candidate_intelligence/test_nonblocking_embedding.py::test_sync_embedding_does_not_block_the_event_loop` verifies the event loop advances during provider work. |
| `backend/app/modules/candidate_intelligence/evidence/providers.py:25,33,48,51` | synchronous provider API | medium | Keep deterministic CPU mocks synchronous, but ensure production providers do not perform blocking network I/O on the request loop. |
| `backend/app/core/config.py:46-47` | hard-coded URLs | low | The localhost CORS origins are development defaults; move deployment origins to typed settings and reject wildcard credentials. |
| `backend/app/modules/candidate_intelligence/evidence/github.py:38,52` | hard-coded service URL | low | Keep the fixed GitHub API host constrained by SSRF policy; move endpoint and limits to typed settings if deployments need overrides. |
| `backend/app/modules/candidate_intelligence/verification/checks.py:130,298,319` | magic numbers | low | Move verification thresholds and HTTP timeout/redirect limits into typed settings; existing threshold settings cover only part of this behavior. |
| `backend/app/modules/candidate_intelligence/models.py:170` | SQL expression | low | `text("created_at DESC")` is used only to define an index; no interpolated raw SQL query was found. Keep request data out of SQL text. |
| `backend/app/models/job_access.py:40` | foreign-key index | low | `granted_by_id` references users without its own index; add only if an observed join/filter query uses it. |
| `backend/app/modules/candidate_intelligence/models.py:145,166,188` | foreign-key index | low | `candidate_score_id` and `triggered_by` references lack dedicated indexes; justify from actual delete/join/filter plans before adding indexes. |
| `backend/app/modules/candidate_intelligence/scoring/category_formulas.py:13-89` | float / Decimal | low | Scoring calculations use Decimal and `ROUND_HALF_UP`; float conversion is limited to API/persistence adapters. Preserve Decimal through the output edge. |
| `backend/app/models/base.py:11`, `backend/app/core/security.py:49,75`, `backend/app/modules/auth/service.py:156,210` | timezone | low | Reviewed clock calls use `datetime.now(timezone.utc)`; mapped timestamp columns inspected use `DateTime(timezone=True)`. No naive `datetime.now()`/`utcnow()` call was found. |
| tracked `backend/.env.example` | secrets / environment files | low | It is the only tracked `.env*` file found; review that it contains placeholders only. Secret scanner unavailable, so secret absence is NOT VERIFIED. |
| untracked `backend/kiran_before_review.dump`, `backend/var/`, and generated local test files | tracked junk | medium | These are not tracked; keep them ignored and do not add the database dump, uploads, caches, or generated databases to Git. |
| tracked migrations `4c8d6f1a2e73`, `7a4d91c2e6b3`, `9b1c4f6e2a71`, `a5475d55ef43`, `f2c3a01d84b7` | dirty migration ancestors | high | These existing revisions are modified in the worktree. Do not rewrite or commit them as Phase 5; inspect ownership before any migration-related work. |
| `backend/app/modules/candidate_intelligence/config.py:28-57` | hard-coded scoring values | low | Weights and similarity bounds are currently typed module settings; preserve their versioned snapshot behavior when centralizing settings. |
| `backend/app/**` | TODO / FIXME / XXX / HACK | low | Search found no matching markers in application or test Python files. |

## Secret and file scan

`git ls-files` found only `.env.example` among `.env*` paths and no tracked dump, SQLite database, `__pycache__`, `.pyc`, upload, or storage artifacts. The worktree contains an untracked dump filename; its contents were not opened or printed. No secret scanner was available, so this is not a credential audit and cannot establish that no credential was committed in history.
