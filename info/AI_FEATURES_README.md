# `ai_features` — drop-in AI module for Job Sentry

One folder: AI layer (**Pydantic AI** runtime + **DSPy** optimizer), resume-ingestion service, candidate/application
endpoints, models, schemas, Celery worker, migration. Copy it into `backend/app/` and wire it with three lines.

```
ai_features/
├── api.py            # the ONE router (resumes + candidates)         -> include this
├── _compat.py        # the ONLY file that knows your repo's names     -> check these 4 imports
├── models/           # Candidate, Application, Resume, ExtractedProfile, IdentitySuggestion
├── schemas/          # API shapes + the structured-extraction schemas
├── ai/               # shared AI layer: settings, engines, DSPy, offline dev model, CLI, compiled/ prompts
├── resumes/          # upload service, parsers (PDF/DOCX/OCR), storage (local/S3), Celery pipeline
├── candidates/       # candidate read service/router
├── migrations/       # Alembic revision (copy it into migrations/versions/)
├── requirements.txt  .env.example  Dockerfile.snippet  docker-compose.override.yml
```

## Add it to the app (≈10 minutes)

**1. Install** — `uv add` the runtime lines from `requirements.txt`. The backend Dockerfile installs `tesseract-ocr` and
its English language data. If Tesseract is installed outside `PATH`, set `RESUMES_TESSERACT_CMD` to its executable path.

**2. Routes** — in `app/main.py`:

```python
from app.ai_features import router as ai_features_router
app.include_router(ai_features_router, prefix=settings.API_V1_STR)   # use your existing API prefix
```

Optional, fail fast on bad AI config (e.g. production with the offline model, or a missing key):

```python
from app.ai_features import startup_check
startup_check()          # in your lifespan/startup
```

**3. Tables** — in `app/models/__init__.py` add one line so Alembic/`create_all` see them:

```python
import app.ai_features.models  # noqa: F401
```

then `cp app/ai_features/migrations/b7d2e9a4c1f5_ai_features.py migrations/versions/`, confirm `down_revision` equals
your head (`alembic heads`; it is set to `4c8d6f1a2e73` from PROJECT_GUIDE.md) and run `alembic upgrade head`.

**4. Config** — append `.env.example` to your `.env`. With **no changes** it runs fully offline (`AI_MODEL=heuristic`).

**5. Worker** (resume processing runs in the background) —
`docker compose -f docker-compose.yml -f app/ai_features/docker-compose.override.yml up --build`
or locally: `celery -A app.ai_features.resumes.celery_app:celery_app worker -Q resumes -l info` and **one**
`... beat -l info`.

**6. (Optional) AI requirement suggestions for Phase 2** — set one env var, no Phase 2 code change:
`AI_REQUIREMENTS_PROVIDER=app.ai_features.ai.requirements:build_provider`

If your Phase 1/2 names differ from PROJECT_GUIDE.md, only `_compat.py` needs editing
(`get_db`, `get_current_active_user`, `settings.DATABASE_URL`, `success_response`, `JobsService.get_job`).

## From laptop to production: change `AI_MODEL`, nothing else

| Stage        | Env                                                                                          | What runs                                                                                      |
|--------------|----------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------|
| Develop / CI | `AI_MODEL=heuristic` (default)                                                               | rule-based, offline, deterministic, **no key, no network**; same Pydantic AI code path as prod |
| Local LLM    | `AI_MODEL=ollama:qwen2.5:7b`                                                                 | free local model                                                                               |
| Production   | `AI_ENV=production` `AI_MODEL=anthropic:claude-sonnet-5-5` `AI_FALLBACK_MODELS=openai:gpt-5` | real model + automatic fallback; **refuses to start with `heuristic`/`test`**                  |

Any Pydantic AI model id works (`provider:model`); provider keys use the providers' standard variables
(`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, ...). Commands (run from `backend/`):

```bash
python -m app.ai_features.ai check                       # config + smoke test: run before every deploy
python -m app.ai_features.ai evaluate -n 30 [--examples labeled.jsonl]   # how good is the CURRENT model/engine?
python -m app.ai_features.ai optimize [--optimizer bootstrap|mipro] [--examples labeled.jsonl] [--min-gain 0.02]
python -m app.ai_features.ai synthesize -n 50 --out samples.jsonl
```

**Recommended path:** build on `heuristic` → `evaluate` with a real model on ~30 *real, consented, anonymised*
labeled resumes (`--examples`) → `optimize` → commit `ai/compiled/resume_profile.json` → deploy with the production env.
The synthetic data shipped here only proves the plumbing; its scores say nothing about real resumes.

## How the AI parts fit together

- **Pydantic AI = runtime.** One `Agent` per task with a Pydantic output type: automatic re-ask when output fails
  validation,
  model fallbacks, per-extraction request cap, provider-independent error mapping, offline test/heuristic models.
- **DSPy = tuning + optional engine.** `optimize` tunes instructions/few-shot examples against a metric (field F1,
  penalising anything not found in the text) on a held-out split and **writes the artifact only if it is not worse than
  baseline**. The artifact is plain JSON that *both* engines load, so **production does not need DSPy installed**
  (tested). `AI_ENGINE=dspy` runs the DSPy program directly (needs `dspy`).
- **Immutable safety rules.** Document text is wrapped in `<document>` tags (wrapper tags in the text are stripped);
  a fixed safety preamble is always prepended — an optimizer cannot remove it; the model's only action is returning a
  structured object. A stale artifact (schema/instructions changed since compiling) is ignored with a warning.
- **Never fabricates.** Null/empty by default; after the model answers, every
  email/phone/URL/name/skill/employer/degree/
  certification/project not traceable to the document text is **removed** (not corrected) and ungrounded evidence quotes
  are cleared with confidence capped; removals are listed in `warnings`. All output is labelled
  `resume_claims_unverified`.
- **Tasks:** `resume_profile` (Phase 3) and `job_requirements` (Phase 2 suggestions; weights normalised so preferred sum
  to
  exactly 1, mandatory = 0). Add a task = one `TaskSpec` in `ai/tasks.py`.

## Endpoints (add your API prefix, normally `/api/v1`)

|                                                   |                                                                                                                                                                               |
|---------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `POST /jobs/{job_id}/resumes`                     | multipart `files` (≤20: PDF/DOCX/JPEG/PNG). **202** with per-file `accepted/duplicate/rejected`; processing is async. Needs company membership or **editor** grant on the job |
| `GET /jobs/{job_id}/applicants`                   | list applicants for a job (candidate details + status + latest resume + profile summary). Needs company membership or **viewer** / **editor** grant                           |
| `GET /resumes/{id}` · `GET /resumes/{id}/status`  | metadata + validated profile · `uploaded→queued→extracting→analyzing→completed/failed`, safe failure code/message                                                             |
| `POST /resumes/{id}/retry`                        | failed (or never-queued) → queued; member or **editor** only; capped at 5 manual retries                                                                                      |
| `GET /applications/{id}` · `GET /candidates/{id}` | application + resumes/profile · candidate + applications + latest profile + identity-review hints                                                                             |

**Access = your Phase 2 rules, reused not re-implemented:** every call goes through `JobsService.get_job(...)`. Company
members: full access. Job-grant users: viewer reads, editor also uploads/retries, only for *that job*. No access ⇒ the
same 404 as "doesn't exist". A grant-only user sees a candidate **only through granted jobs**; other jobs' applications,
profiles and identity-review hints (which point at other candidates) are withheld.

## Behaviour guarantees (all covered by tests)

Validation by size + extension + magic bytes (macro/zip-bomb DOCX and oversized images rejected) · SHA-256 · originals
stored outside the DB (local or S3) under server-generated keys · parsing/AI only in workers · row-locked lease so
duplicate
deliveries skip · each stage persists its result so retries don't repeat OCR/LLM · atomic finalize · identical file ⇒
same
resume (race-safe) · failures store only a code + canned message (never exception text; logs record exception *type*
only) ·
**identity is cautious:** auto-link only on one same-company candidate with the same normalized email, non-conflicting
names, not already applied to that job; everything else is a separate candidate + a pending suggestion for a human.

## Tests

`cd backend && PYTHONPATH=tests/ai_features/sandbox_repo pytest tests/ai_features` (SQLite).
For PostgreSQL (also enables the 3 concurrency-race tests):
`TEST_DATABASE_URL=postgresql+asyncpg://… pytest tests/ai_features`.
`tests/ai_features/sandbox_repo/` is a stand-in for your Phase 1/2 code rebuilt from PROJECT_GUIDE.md — in your repo
drop that
`PYTHONPATH`, and adapt the three factory functions at the top of `tests/ai_features/resumes/helpers.py`
(`make_company/make_user/make_job`) to your real models' required columns.

## What was and wasn't verified

**Ran and passed (127 tests on PostgreSQL 16 + asyncpg, 124 + 3 skipped on SQLite):** the full pipeline, real Tesseract
OCR,
Pydantic AI retries/fallback/error mapping (scripted models), prompt-injection wrapping, compiled-artifact loading
(including with DSPy import blocked), DSPy engine/optimizer/CLI end to end (offline LM), access rules incl.
viewer/editor/
outsider/cross-company (each rule mutation-tested), migration vs ORM on SQLite and PostgreSQL (up and down), Celery
wiring in eager mode.

**Not verified:** against your real Phase 1/2 code (only a reconstruction from the guide — `_compat.py` is where a
mismatch
would show), any real LLM provider (no API keys here: Anthropic/OpenAI/Ollama paths are covered with scripted models
only),
DSPy's `mipro` optimizer (only `bootstrap` was run), real S3/MinIO (moto only), the Docker/Compose files, Celery with a
real
Redis, and extraction quality on real resumes. The offline heuristic is a dev tool, not a quality baseline.

## Limitations

- OCR has no deskew/layout analysis; install extra Tesseract language packs for non-English.
- Confidence values are model-reported, not calibrated; "evidence" is checked as a quote, not proof.
- Full resume text is stored in Postgres (retry cache + evidence); sensitive. No delete/download endpoints yet (Phase
  5).
- Optimized few-shot demos add prompt length (≈ several KB per call); keep `--examples` small and recompile when the
  schema changes.
- Run **one** `beat`. Keep `RESUMES_LEASE_SECONDS` > the task hard time limit (330 s default).
- Phase 2 `AI_REQUIREMENTS_PROVIDER` returns
  `{"requirements":[{category,name,requirement_type,importance,weight,is_mandatory}]}`;
  if your `validate_extraction` expects another wrapper, change `to_payload()` in `ai/requirements.py` (one function).
